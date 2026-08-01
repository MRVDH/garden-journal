"""Pruning calendar: every plant's windows projected as all-day events (3.4).

One entity for the whole integration, with no device. Each pruning window recurs
every year, so an occurrence is projected for each year overlapping the range
Home Assistant asks for. End dates are exclusive, following the iCal all-day
convention, so a window running to 31 August ends on 1 September. The base class
reschedules the entity's on/off state at each event's boundaries, which for
all-day events fall at local midnight, so no clock is read here.

An event's summary is translated, so a Dutch instance does not read "Prune Roos"
above a Dutch description. The whole line including its word order comes from the
translation files, since Dutch puts the verb last.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .dataset import GardenCompanionConfigEntry
from .models import Window
from .resolver import Resolver, resolve_windows
from .windows import next_pruning, occurrence_end, occurrences_in_range

# The category is this integration's own, which `onboarding` does for its area and
# dashboard names too. English is loaded first as a fallback and the user's
# language overlays it, so a language file missing the key still reads sensibly.
_SUMMARY_CATEGORY = "calendar_event"
_SUMMARY_KEY = f"component.{DOMAIN}.{_SUMMARY_CATEGORY}.prune"
_SUMMARY_FALLBACK = "Prune {name}"


def _description(window: Window, language: str) -> str:
    """Return the window's description in the user's language, else English."""
    return (
        window.description.get(language)
        or window.description.get("en")
        or next(iter(window.description.values()), "")
    )


async def _summary_template(hass: HomeAssistant) -> str:
    """Return the localised "Prune {name}" template for an event summary.

    Fetched once at setup because `event` is a sync property and translations load
    asynchronously. A language change needs a restart, which is already true of
    entity names.
    """
    translations = await async_get_translations(
        hass, hass.config.language, _SUMMARY_CATEGORY, {DOMAIN}
    )
    return translations.get(_SUMMARY_KEY, _SUMMARY_FALLBACK)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the single pruning calendar for all plants."""
    resolver = Resolver(entry.runtime_data.species)
    plants = [
        (subentry.subentry_id, subentry.title, dict(subentry.data))
        for subentry in entry.get_subentries_of_type("plant")
    ]
    summary = await _summary_template(hass)
    async_add_entities([PruningCalendar(entry.entry_id, plants, resolver, summary)])


class PruningCalendar(CalendarEntity):
    """Every plant's pruning windows on one calendar (3.4)."""

    _attr_has_entity_name = True
    _attr_translation_key = "garden_companion"
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        plants: list[tuple[str, str, dict[str, Any]]],
        resolver: Resolver,
        summary: str,
    ) -> None:
        """Set up the calendar over a snapshot of the current plants."""
        self._plants = plants
        self._resolver = resolver
        self._summary = summary
        self._attr_unique_id = f"{entry_id}_calendar"

    def _plant_windows(self) -> list[tuple[str, str, list[Window]]]:
        """Return (subentry id, title, windows) for each plant with known timing."""
        resolved = []
        for subentry_id, title, data in self._plants:
            windows = resolve_windows(data, self._resolver)
            if windows:
                resolved.append((subentry_id, title, windows))
        return resolved

    def _event(
        self, subentry_id: str, title: str, window: Window, index: int, start: Any
    ) -> CalendarEvent:
        """Build an all-day event for one window occurrence."""
        end = occurrence_end(window, start) + timedelta(days=1)
        return CalendarEvent(
            start=start,
            end=end,
            summary=self._summary.format(name=title),
            description=_description(window, self.hass.config.language),
            uid=f"{subentry_id}-{index}-{start.year}",
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the pruning happening now, else the soonest upcoming one (3.4)."""
        today = dt_util.now().date()
        best: tuple[Any, str, str, Window, int] | None = None
        for subentry_id, title, windows in self._plant_windows():
            start, window = next_pruning(windows, today)
            if best is None or start < best[0]:
                best = (start, subentry_id, title, window, windows.index(window))
        if best is None:
            return None
        start, subentry_id, title, window, index = best
        return self._event(subentry_id, title, window, index, start)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return every window occurrence overlapping the requested range (3.4)."""
        range_start = dt_util.as_local(start_date).date()
        range_end = dt_util.as_local(end_date).date()
        events: list[CalendarEvent] = []
        for subentry_id, title, windows in self._plant_windows():
            for index, window in enumerate(windows):
                for _year, start, _end in occurrences_in_range(
                    window, range_start, range_end
                ):
                    events.append(self._event(subentry_id, title, window, index, start))
        return events
