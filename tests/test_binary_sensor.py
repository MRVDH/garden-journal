"""Tests for the prune-now and care-now binary sensors (step 7, 2.9).

Time is frozen so the on/off state is deterministic against the packaged dataset
(Wisteria prunes mid-July to end of August; Hydrangea paniculata in spring; Rosa
is the row with a care season, June to mid-October).
"""

from __future__ import annotations

from typing import Any

from freezegun import freeze_time
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garden_companion.const import DOMAIN


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


async def test_prune_now_tracks_whether_today_is_inside_a_window(
    hass: HomeAssistant,
) -> None:
    """In early August, wisteria's window is open and the hydrangea's is not."""
    with freeze_time("2026-08-01"):
        await _setup(
            hass,
            [
                ("My wisteria", _plant("Wisteria", None)),
                ("My hydrangea", _plant("Hydrangea", "paniculata")),
            ],
        )
        wisteria = hass.states.get("binary_sensor.my_wisteria_prune_now")
        hydrangea = hass.states.get("binary_sensor.my_hydrangea_prune_now")
        assert wisteria is not None
        assert wisteria.state == "on"
        assert wisteria.attributes["icon"] == "mdi:content-cut"
        assert hydrangea is not None
        assert hydrangea.state == "off"


async def test_care_now_is_on_inside_the_care_season(hass: HomeAssistant) -> None:
    """In August the rose's deadheading season is open, with the advice attached."""
    with freeze_time("2026-08-01"):
        await _setup(hass, [("My rose", _plant("Rosa", None))])
        care = hass.states.get("binary_sensor.my_rose_ongoing_care")
        assert care is not None
        assert care.state == "on"
        assert care.attributes["icon"] == "mdi:flower-outline"
        assert "five leaflets" in care.attributes["description"]
        assert care.attributes["season_start"] == "06-01"
        assert care.attributes["season_end"] == "10-15"


async def test_care_now_is_off_outside_the_care_season(hass: HomeAssistant) -> None:
    """In December the season is shut, and the advice is not offered."""
    with freeze_time("2026-12-01"):
        await _setup(hass, [("My rose", _plant("Rosa", None))])
        care = hass.states.get("binary_sensor.my_rose_ongoing_care")
        assert care is not None
        assert care.state == "off"
        assert care.attributes["description"] is None


async def test_a_plant_without_care_gets_no_care_sensor(hass: HomeAssistant) -> None:
    """Most plants have no continuous care, so they get no entity that never turns on."""
    await _setup(hass, [("My wisteria", _plant("Wisteria", None))])
    assert hass.states.get("binary_sensor.my_wisteria_prune_now") is not None
    assert hass.states.get("binary_sensor.my_wisteria_ongoing_care") is None
