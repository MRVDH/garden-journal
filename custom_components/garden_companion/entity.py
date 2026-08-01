"""Shared base for a plant's entities: its device and a midnight recompute.

Both the next-pruning sensor and the prune-now binary sensor derive their value
from what "today" is, so both refresh at local midnight (3.5). The set of plants
changing (add, reconfigure, remove) is handled by reloading the config entry, not
here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_change

from .const import DOMAIN
from .models import Care, Window
from .resolver import Resolver, resolve_care, resolve_windows


def plant_device_info(subentry_id: str, title: str) -> DeviceInfo:
    """Return the device that a plant's entities share."""
    return DeviceInfo(
        identifiers={(DOMAIN, subentry_id)},
        name=title,
        entry_type=DeviceEntryType.SERVICE,
    )


class PlantEntity(Entity):
    """Base for a plant's entities, sharing the device and the daily refresh."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, subentry_id: str, title: str, data: dict[str, Any], resolver: Resolver
    ) -> None:
        """Set up the shared device and resolver for one plant."""
        self._data = data
        self._resolver = resolver
        self._attr_device_info = plant_device_info(subentry_id, title)

    async def async_added_to_hass(self) -> None:
        """Recompute state at local midnight, when today rolls over (3.5)."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._recompute, hour=0, minute=0, second=0
            )
        )

    @callback
    def _recompute(self, now: datetime) -> None:
        """Write fresh state after midnight."""
        self.async_write_ha_state()

    def _windows(self) -> list[Window] | None:
        """Resolve this plant's effective windows, or None on a repair case (3.2)."""
        return resolve_windows(self._data, self._resolver)

    def _care(self) -> list[Care]:
        """Resolve this plant's continuous-care seasons, empty when it has none (2.9)."""
        return resolve_care(self._data, self._resolver)
