"""Tests for the plant subentry flow: search, disambiguation, naming (step 5).

These drive the real subentry flow through hass.config_entries.subentries. The
dataset is injected into the entry's runtime data, so disambiguation can be
exercised even though the shipped three-row fixture has no ambiguous genus.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garden_companion.const import DOMAIN
from custom_components.garden_companion.dataset import GardenCompanionData
from custom_components.garden_companion.models import build_dataset


def _window(start: str, end: str) -> dict[str, Any]:
    """Build one window dict."""
    return {
        "when": {"start": start, "end": end},
        "description": {"nl": "nl", "en": "en"},
    }


def _row(
    genus: str,
    windows: list[dict[str, Any]],
    *,
    species: str | None = None,
    variant: str | None = None,
    names: dict[str, list[str]] | None = None,
    distinguish: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one record dict, defaulting the required fields."""
    row: dict[str, Any] = {
        "genus": genus,
        "names": names or {"nl": [genus.lower()], "en": [genus.lower()]},
        "source": "https://example.org",
        "windows": windows,
    }
    if species is not None:
        row["species"] = species
    if variant is not None:
        row["variant"] = variant
    if distinguish is not None:
        row["distinguish"] = distinguish
    return row


_SPRING = _window("03-01", "04-15")
_APRIL = _window("04-01", "04-30")
_SUMMER = _window("07-15", "08-31")


async def _entry_with(hass: HomeAssistant, rows: list[dict[str, Any]]) -> ConfigEntry:
    """Set up a config entry, then swap in a dataset built from rows."""
    species, errors = build_dataset(rows)
    assert errors == []
    entry = MockConfigEntry(domain=DOMAIN, title="Garden Companion", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data = GardenCompanionData(species=species)
    return entry


async def _start(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Start the add-plant subentry flow and return its first step."""
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "plant"), context={"source": "user"}
    )


async def test_add_a_dataset_plant(hass: HomeAssistant) -> None:
    """A single match advances to naming and creates a subentry with 3.2 data."""
    entry = await _entry_with(
        hass,
        [
            _row(
                "Hydrangea",
                [_SPRING],
                species="paniculata",
                names={"nl": ["Pluimhortensia"], "en": ["Panicle hydrangea"]},
            )
        ],
    )
    result = await _start(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "hortensia"}
    )
    assert result["step_id"] == "name"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"display_name": "By the shed"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "By the shed"
    assert result["data"]["genus"] == "Hydrangea"
    assert result["data"]["species"] == "paniculata"
    assert result["data"]["matched_on"] == "species"
    assert result["data"]["in_dataset"] is True


async def test_distinct_timings_ask_then_create(hass: HomeAssistant) -> None:
    """A genus whose species disagree shows a choice, then creates the picked one."""
    entry = await _entry_with(
        hass,
        [
            _row("Hydrangea", [_SPRING], species="paniculata"),
            _row("Hydrangea", [_APRIL], species="macrophylla"),
        ],
    )
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "hydrangea"}
    )
    assert result["step_id"] == "disambiguate"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"choice": "0"}
    )
    assert result["step_id"] == "name"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"display_name": "H"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["genus"] == "Hydrangea"


async def test_not_sure_goes_to_manual(hass: HomeAssistant) -> None:
    """The 'I am not sure' option routes into manual add."""
    entry = await _entry_with(
        hass,
        [
            _row("Hydrangea", [_SPRING], species="paniculata"),
            _row("Hydrangea", [_APRIL], species="macrophylla"),
        ],
    )
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "hydrangea"}
    )
    assert result["step_id"] == "disambiguate"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"choice": "unsure"}
    )
    assert result["step_id"] == "manual"


async def test_shared_timing_does_not_ask(hass: HomeAssistant) -> None:
    """Rows with the same timing (laurier) advance straight to naming."""
    entry = await _entry_with(
        hass,
        [
            _row(
                "Prunus",
                [_SUMMER],
                species="laurocerasus",
                names={"nl": ["Laurier"], "en": ["Cherry laurel"]},
            ),
            _row(
                "Laurus",
                [_SUMMER],
                species="nobilis",
                names={"nl": ["Laurier"], "en": ["Bay laurel"]},
            ),
        ],
    )
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "laurier"}
    )
    assert result["step_id"] == "name"


async def test_no_match_goes_to_manual(hass: HomeAssistant) -> None:
    """A name not in the dataset routes into manual add."""
    entry = await _entry_with(
        hass, [_row("Hydrangea", [_SPRING], species="paniculata")]
    )
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "quercus robur"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


async def test_manual_borrow_creates_a_plant(hass: HomeAssistant) -> None:
    """Manual add with borrow stores windows_like and marks the plant not-in-dataset."""
    entry = await _entry_with(
        hass,
        [
            _row(
                "Wisteria",
                [_SUMMER],
                names={"nl": ["Blauwe regen"], "en": ["Wisteria"]},
            )
        ],
    )
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "Quercus robur"}
    )
    assert result["step_id"] == "manual"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"botanical": "Quercus robur", "display_name": "The oak"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "timing"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "borrow"}
    )
    assert result["step_id"] == "borrow"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"borrowed": "0"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "The oak"
    data = result["data"]
    assert data["genus"] == "Quercus"
    assert data["species"] == "robur"
    assert data["matched_on"] == "manual"
    assert data["in_dataset"] is False
    assert data["windows_like"] == {
        "genus": "Wisteria",
        "species": None,
        "variant": None,
    }


async def test_author_is_not_ready(hass: HomeAssistant) -> None:
    """Choosing to author your own timing aborts until that slice exists."""
    entry = await _entry_with(hass, [_row("Wisteria", [_SUMMER])])
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "Quercus"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"botanical": "Quercus", "display_name": "Oak"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "author"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "author_not_ready"
