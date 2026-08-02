"""Tests for the pruning calendar.

One calendar aggregates every plant's windows. Time is frozen so the current
event is deterministic against the packaged dataset (Wisteria prunes mid-July to
end of August and again in late winter; Hydrangea paniculata in spring).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from freezegun import freeze_time
from homeassistant.components.calendar import CalendarEntity
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garden_companion.const import DOMAIN

_ENTITY_ID = "calendar.garden_companion"


def _plant(genus: str, species: str | None) -> dict[str, Any]:
    """Return stored data for a dataset plant."""
    return {
        "genus": genus,
        "species": species,
        "display_name": "unused",
        "matched_on": "genus" if species is None else "species",
        "in_dataset": True,
        "windows_like": None,
        "windows": None,
        "source": None,
        "image_url": None,
    }


async def _setup(hass: HomeAssistant, plants: list[tuple[str, dict[str, Any]]]) -> None:
    """Set up the integration with the given (title, data) plant subentries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Companion",
        subentries_data=[
            ConfigSubentryData(
                subentry_type="plant", title=title, data=data, unique_id=None
            )
            for title, data in plants
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _calendar(hass: HomeAssistant) -> CalendarEntity:
    """Return the single pruning calendar entity."""
    entity = hass.data[DATA_INSTANCES]["calendar"].get_entity(_ENTITY_ID)
    assert isinstance(entity, CalendarEntity)
    return entity


async def test_events_project_every_plant_across_a_year(hass: HomeAssistant) -> None:
    """A full-year range yields each window once, all-day, with an exclusive end."""
    await _setup(
        hass,
        [
            ("My wisteria", _plant("Wisteria", None)),
            ("My hydrangea", _plant("Hydrangea", "paniculata")),
        ],
    )
    assert hass.states.get(_ENTITY_ID) is not None

    events = await _calendar(hass).async_get_events(
        hass,
        datetime(2026, 1, 1, tzinfo=dt_util.UTC),
        datetime(2027, 1, 1, tzinfo=dt_util.UTC),
    )
    spans = sorted((e.summary, e.start, e.end) for e in events)
    assert spans == [
        ("Prune My hydrangea", date(2026, 3, 1), date(2026, 4, 16)),
        ("Prune My wisteria", date(2026, 1, 15), date(2026, 2, 16)),
        ("Prune My wisteria", date(2026, 7, 15), date(2026, 9, 1)),
    ]
    assert all(e.all_day for e in events)


async def test_event_is_the_active_or_next_pruning(hass: HomeAssistant) -> None:
    """On 1 August the open wisteria window is the calendar's current event."""
    with freeze_time("2026-08-01"):
        await _setup(hass, [("My wisteria", _plant("Wisteria", None))])
        event = _calendar(hass).event
        assert event is not None
        assert event.summary == "Prune My wisteria"
        assert event.start == date(2026, 7, 15)
        assert event.end == date(2026, 9, 1)
        assert hass.states.get(_ENTITY_ID).state == "on"


async def test_event_summary_is_translated(hass: HomeAssistant) -> None:
    """On a Dutch instance the summary reads Dutch, verb last, not "Prune ..."."""
    hass.config.language = "nl"
    await _setup(hass, [("De blauwe regen", _plant("Wisteria", None))])

    events = await _calendar(hass).async_get_events(
        hass,
        datetime(2026, 1, 1, tzinfo=dt_util.UTC),
        datetime(2026, 3, 1, tzinfo=dt_util.UTC),
    )
    assert [event.summary for event in events] == ["De blauwe regen snoeien"]


async def test_no_plants_means_no_event(hass: HomeAssistant) -> None:
    """With no plants the calendar exists but has no current event."""
    await _setup(hass, [])
    assert hass.states.get(_ENTITY_ID) is not None
    assert _calendar(hass).event is None
    assert hass.states.get(_ENTITY_ID).state == "off"
