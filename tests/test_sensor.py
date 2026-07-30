"""Tests for the next-pruning sensor entity (step 6).

The plant is preloaded as a subentry so the sensor platform creates it at setup.
The dataset is the packaged three-row fixture, so the subentry references a plant
that is in it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garden_companion.const import DOMAIN


def _plant_data(genus: str, species: str | None) -> dict[str, Any]:
    """Return stored data for a dataset plant."""
    return {
        "genus": genus,
        "species": species,
        "variant": None,
        "display_name": "unused",
        "matched_on": "species",
        "in_dataset": True,
        "windows_like": None,
        "windows": None,
        "source": None,
        "image_url": None,
    }


async def _setup_with_plant(
    hass: HomeAssistant, title: str, data: dict[str, Any]
) -> None:
    """Set up the integration with one preloaded plant subentry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Companion",
        subentries_data=[
            ConfigSubentryData(
                subentry_type="plant", title=title, data=data, unique_id=None
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_dataset_plant_gets_a_next_pruning_sensor(hass: HomeAssistant) -> None:
    """A dataset plant gets a date-valued sensor with the expected attributes."""
    await _setup_with_plant(hass, "By the shed", _plant_data("Hydrangea", "paniculata"))

    state = hass.states.get("sensor.by_the_shed_next_pruning")
    assert state is not None
    assert state.state not in ("unknown", "unavailable")
    assert state.attributes["device_class"] == "date"
    assert state.attributes["botanical_name"] == "Hydrangea paniculata"
    assert state.attributes["matched_on"] == "species"
    assert state.attributes["in_dataset"] is True
    assert "window_end" in state.attributes
    assert state.attributes["description"]


async def test_unknown_plant_sensor_is_unknown(hass: HomeAssistant) -> None:
    """A stored plant not in the dataset resolves to an unknown state, not an error."""
    await _setup_with_plant(hass, "Mystery", _plant_data("Quercus", "robur"))

    state = hass.states.get("sensor.mystery_next_pruning")
    assert state is not None
    assert state.state == "unknown"
    assert state.attributes["botanical_name"] == "Quercus robur"


async def test_adding_a_plant_creates_its_entities(hass: HomeAssistant) -> None:
    """Adding a plant reloads the entry so its entities appear without a restart."""
    entry = MockConfigEntry(domain=DOMAIN, title="Garden Companion")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "plant"), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "hortensia"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"display_name": "New plant"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert hass.states.get("sensor.new_plant_next_pruning") is not None
    assert hass.states.get("binary_sensor.new_plant_prune_now") is not None
