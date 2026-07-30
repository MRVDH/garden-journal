"""Tests for the prune-now binary sensor (step 7).

Time is frozen so the on/off state is deterministic against the packaged dataset
(Wisteria prunes mid-July to end of August; Hydrangea paniculata in spring).
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
        "variant": None,
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
