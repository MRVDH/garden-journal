"""Two binary sensors per plant: is it pruning time, and is care season open (3.3).

Prune-now, read together with the next-pruning sensor, says the job is open and
when it opened. Care-now says a continuous job like deadheading applies right now,
which has no date to put in a calendar. Both are computed locally and refresh at
local midnight (see the base entity).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .dataset import GardenCompanionConfigEntry
from .entity import PlantEntity
from .models import Care
from .resolver import Resolver, resolve_care
from .windows import in_season


def _describe(care: Care, language: str) -> str:
    """Return a care season's advice in the user's language, else English."""
    return (
        care.description.get(language)
        or care.description.get("en")
        or next(iter(care.description.values()), "")
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the binary sensors for each plant subentry.

    Prune-now exists for every plant. Care-now only exists for a plant that has
    continuous care to do, since most plants have none and an entity that can
    never turn on is clutter on the device page. A dataset update that adds care
    to a plant already in the garden needs a reload to create it, the same as any
    other change to the set of entities.
    """
    resolver = Resolver(entry.runtime_data.species)
    for subentry in entry.get_subentries_of_type("plant"):
        data = dict(subentry.data)
        entities: list[BinarySensorEntity] = [
            PruneNowBinarySensor(subentry.subentry_id, subentry.title, data, resolver)
        ]
        if resolve_care(data, resolver):
            entities.append(
                CareNowBinarySensor(
                    subentry.subentry_id, subentry.title, data, resolver
                )
            )
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)


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
        return in_season(windows, dt_util.now().date())


class CareNowBinarySensor(PlantEntity, BinarySensorEntity):
    """On while a continuous-care season is open, deadheading a rose say (2.9, 3.3).

    This is deliberately not a calendar event. A season runs for months, so it
    would sit over the pruning windows and hide them, and an automation on the
    calendar would fire all summer. A state to test is the honest shape for work
    that has no date.
    """

    _attr_translation_key = "care_now"
    _attr_icon = "mdi:flower-outline"

    def __init__(
        self, subentry_id: str, title: str, data: dict[str, Any], resolver: Resolver
    ) -> None:
        """Set up the binary sensor for one plant."""
        super().__init__(subentry_id, title, data, resolver)
        self._attr_unique_id = f"{subentry_id}_care_now"

    def _open(self) -> list[Care]:
        """Return the care seasons that are open today."""
        today = dt_util.now().date()
        return [care for care in self._care() if in_season([care], today)]

    @property
    def is_on(self) -> bool:
        """Return whether any of the plant's care seasons is open today."""
        return bool(self._open())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return what to do, and the season it runs in.

        Only the open seasons are described, so a template reading `description`
        while the sensor is on gets the advice that applies now.
        """
        open_now = self._open()
        return {
            "description": " ".join(
                _describe(care, self.hass.config.language) for care in open_now
            )
            or None,
            "season_start": open_now[0].start if open_now else None,
            "season_end": open_now[0].end if open_now else None,
        }
