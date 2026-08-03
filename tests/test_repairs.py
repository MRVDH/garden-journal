"""Tests for the repair path.

A plant whose stored key no longer matches a dataset row raises a repair issue
and its entities read unknown, while the integration still loads. A plant that
resolves raises nothing, and removing a plant clears its issue.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garden_journal.const import DOMAIN


def _plant(genus: str, species: str | None) -> dict[str, Any]:
    """Return stored data for a dataset plant."""
    return {
        "genus": genus,
        "species": species,
        "display_name": "unused",
        "matched_on": "species" if species else "genus",
        "in_dataset": True,
        "windows_like": None,
        "windows": None,
        "source": None,
        "image_url": None,
    }


async def _setup(
    hass: HomeAssistant, plants: list[tuple[str, dict[str, Any]]]
) -> MockConfigEntry:
    """Set up the integration with the given (title, data) plant subentries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Journal",
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
    return entry


async def test_unresolved_plant_raises_a_repair_and_reads_unknown(
    hass: HomeAssistant,
) -> None:
    """A plant not in the dataset gets a repair and an unknown sensor, still loaded."""
    entry = await _setup(hass, [("Backyard oak", _plant("Quercus", "robur"))])
    subentry_id = next(iter(entry.subentries))

    issue = ir.async_get(hass).async_get_issue(DOMAIN, subentry_id)
    assert issue is not None
    assert issue.translation_key == "missing_row"
    assert issue.translation_placeholders == {"name": "Backyard oak"}
    assert hass.states.get("sensor.backyard_oak_next_pruning").state == "unknown"


async def test_resolvable_plant_raises_no_repair(hass: HomeAssistant) -> None:
    """A plant that resolves against the dataset raises no repair."""
    entry = await _setup(hass, [("By the shed", _plant("Hydrangea", "paniculata"))])
    subentry_id = next(iter(entry.subentries))
    assert ir.async_get(hass).async_get_issue(DOMAIN, subentry_id) is None


async def test_removing_a_plant_clears_its_repair(hass: HomeAssistant) -> None:
    """Removing an unresolved plant clears its repair on reload."""
    entry = await _setup(hass, [("Backyard oak", _plant("Quercus", "robur"))])
    subentry_id = next(iter(entry.subentries))
    assert ir.async_get(hass).async_get_issue(DOMAIN, subentry_id) is not None

    hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, subentry_id) is None
