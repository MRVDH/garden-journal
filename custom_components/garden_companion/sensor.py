"""Next-pruning sensor: one per plant, the date it should next be pruned (3.3).

The value is computed locally from the resolved windows; there is no polling and
no coordinator (3.5). It refreshes at local midnight (see the base entity) and
when the config entry reloads on a plant change.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .dataset import GardenCompanionConfigEntry
from .entity import PlantEntity
from .models import Window
from .resolver import Resolver
from .windows import next_pruning, occurrence_end


def _pick_description(window: Window, language: str) -> str:
    """Return the window's description in the user's language, else English."""
    return (
        window.description.get(language)
        or window.description.get("en")
        or next(iter(window.description.values()), "")
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a next-pruning sensor for each plant subentry."""
    resolver = Resolver(entry.runtime_data.species)
    for subentry in entry.get_subentries_of_type("plant"):
        async_add_entities(
            [
                NextPruningSensor(
                    subentry.subentry_id, subentry.title, dict(subentry.data), resolver
                )
            ],
            config_subentry_id=subentry.subentry_id,
        )


class NextPruningSensor(PlantEntity, SensorEntity):
    """The date a plant should next be pruned (3.3)."""

    _attr_translation_key = "next_pruning"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self, subentry_id: str, title: str, data: dict[str, Any], resolver: Resolver
    ) -> None:
        """Set up the sensor for one plant."""
        super().__init__(subentry_id, title, data, resolver)
        self._attr_unique_id = f"{subentry_id}_next_pruning"

    def _current(self) -> tuple[date, Window] | None:
        """Return the (start date, window) of the next pruning, or None if unknown."""
        windows = self._windows()
        if not windows:
            return None
        return next_pruning(windows, dt_util.now().date())

    @property
    def native_value(self) -> date | None:
        """Return the next-pruning date, or None when the timing is unknown."""
        current = self._current()
        return current[0] if current else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the window end, description and provenance (3.3)."""
        attributes: dict[str, Any] = {
            "botanical_name": self._botanical_name(),
            "matched_on": self._data.get("matched_on"),
            "in_dataset": self._data.get("in_dataset"),
        }
        current = self._current()
        if current is not None:
            start, window = current
            attributes["window_end"] = occurrence_end(window, start).isoformat()
            attributes["description"] = _pick_description(
                window, self.hass.config.language
            )
        return attributes

    def _botanical_name(self) -> str:
        """Return the plant's botanical name for display."""
        parts = [self._data["genus"]]
        if self._data.get("species"):
            parts.append(self._data["species"])
        return " ".join(parts)
