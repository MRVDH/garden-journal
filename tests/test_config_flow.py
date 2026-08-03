"""Tests for the plant subentry flow: the add signpost, and reconfigure.

Plants are added in the panel, covered by tests/test_panel.py. What this drives is
the flow Home Assistant still shows on the integration page: an add step that
points at the panel, and reconfigure, which re-points an existing plant at a
different dataset row.

Plants are seeded straight onto the config entry rather than created through a
flow, since no flow creates them. The dataset is injected into the entry's runtime
data so an ambiguous genus can be exercised, which the packaged dataset's own rows
cannot always provide.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garden_journal.const import DOMAIN
from custom_components.garden_journal.dataset import GardenJournalData
from custom_components.garden_journal.models import build_dataset


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
    names: dict[str, list[str]] | None = None,
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
    return row


def _plant(genus: str, species: str | None, display_name: str) -> dict[str, Any]:
    """Return stored subentry data for a dataset plant."""
    return {
        "genus": genus,
        "species": species,
        "display_name": display_name,
        "matched_on": "genus" if species is None else "species",
        "in_dataset": True,
        "windows_like": None,
        "windows": None,
        "source": None,
        "image_url": None,
    }


_SPRING = _window("03-01", "04-15")
_APRIL = _window("04-01", "04-30")


async def _entry_with(
    hass: HomeAssistant,
    rows: list[dict[str, Any]],
    plants: list[dict[str, Any]] | None = None,
) -> ConfigEntry:
    """Set up an entry holding the given plants, with a dataset built from rows."""
    species, errors = build_dataset(rows)
    assert errors == []
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Journal",
        data={},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="plant",
                title=plant["display_name"],
                data=plant,
                unique_id=None,
            )
            for plant in plants or []
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data = GardenJournalData(species=species)
    return entry


async def _reconfigure(
    hass: HomeAssistant, entry: ConfigEntry, subentry_id: str
) -> dict[str, Any]:
    """Start the reconfigure flow for one plant and return its first step."""
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "plant"),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )


async def test_the_add_step_points_at_the_panel(hass: HomeAssistant) -> None:
    """The Add plant button aborts with a pointer to the panel rather than a form."""
    entry = await _entry_with(
        hass, [_row("Hydrangea", [_SPRING], species="paniculata")]
    )

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "plant"), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "add_from_panel"


async def test_the_plant_subentry_type_stays_declared(hass: HomeAssistant) -> None:
    """Reconfigure only exists while the subentry type is declared, so assert it is.

    Home Assistant refuses any subentry flow whose type an integration does not
    declare, so dropping the declaration to hide the Add plant button would take
    reconfigure with it.
    """
    entry = await _entry_with(
        hass, [_row("Hydrangea", [_SPRING], species="paniculata")]
    )

    assert "plant" in entry.supported_subentry_types
    assert entry.supported_subentry_types["plant"]["supports_reconfigure"] is True


async def test_reconfigure_repicks_the_species(hass: HomeAssistant) -> None:
    """Reconfigure re-maps a plant to a different species, keeping its name."""
    rows = [
        _row("Hydrangea", [_SPRING], species="paniculata"),
        _row("Hydrangea", [_APRIL], species="macrophylla"),
    ]
    entry = await _entry_with(
        hass, rows, plants=[_plant("Hydrangea", "paniculata", "Mine")]
    )
    subentry_id = next(iter(entry.subentries))

    result = await _reconfigure(hass, entry, subentry_id)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "hydrangea"}
    )
    assert result["step_id"] == "disambiguate"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"choice": "1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    data = entry.subentries[subentry_id].data
    assert data["species"] == "macrophylla"
    assert data["matched_on"] == "species"
    assert data["in_dataset"] is True
    assert data["display_name"] == "Mine"


async def test_reconfigure_offers_no_way_out_to_manual(hass: HomeAssistant) -> None:
    """Every disambiguation option is a dataset row, since the plant already exists."""
    rows = [
        _row("Hydrangea", [_SPRING], species="paniculata"),
        _row("Hydrangea", [_APRIL], species="macrophylla"),
    ]
    entry = await _entry_with(hass, rows, plants=[_plant("Hydrangea", None, "Mine")])
    subentry_id = next(iter(entry.subentries))

    result = await _reconfigure(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "hydrangea"}
    )
    assert result["step_id"] == "disambiguate"

    options = result["data_schema"].schema["choice"].config["options"]
    values = [option["value"] for option in options]
    assert values == ["0", "1"]


async def test_reconfigure_one_match_applies_without_asking(
    hass: HomeAssistant,
) -> None:
    """A search resolving to one timing re-points the plant with no further step."""
    rows = [
        _row("Hydrangea", [_SPRING], species="paniculata"),
        _row("Wisteria", [_APRIL]),
    ]
    entry = await _entry_with(
        hass, rows, plants=[_plant("Hydrangea", "paniculata", "Mine")]
    )
    subentry_id = next(iter(entry.subentries))

    result = await _reconfigure(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "wisteria"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    data = entry.subentries[subentry_id].data
    assert data["genus"] == "Wisteria"
    assert data["species"] is None
    assert data["matched_on"] == "genus"


async def test_reconfigure_clears_manual_timing(hass: HomeAssistant) -> None:
    """Re-pointing a manual plant at a dataset row drops its own authored timing."""
    manual = {
        "genus": "Quercus",
        "species": "robur",
        "display_name": "The oak",
        "matched_on": "manual",
        "in_dataset": False,
        "windows_like": None,
        "windows": [_window("05-01", "05-31")],
        "source": "https://example.org/oak",
        "image_url": None,
    }
    entry = await _entry_with(
        hass, [_row("Hydrangea", [_SPRING], species="paniculata")], plants=[manual]
    )
    subentry_id = next(iter(entry.subentries))

    result = await _reconfigure(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "hydrangea"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    data = entry.subentries[subentry_id].data
    assert data["in_dataset"] is True
    assert data["windows"] is None
    assert data["windows_like"] is None
    assert data["genus"] == "Hydrangea"


async def test_reconfigure_no_match_shows_error(hass: HomeAssistant) -> None:
    """Reconfigure with a name not in the dataset re-shows the step with an error."""
    entry = await _entry_with(
        hass,
        [_row("Hydrangea", [_SPRING], species="paniculata")],
        plants=[_plant("Hydrangea", "paniculata", "Mine")],
    )
    subentry_id = next(iter(entry.subentries))

    result = await _reconfigure(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "quercus"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "not_found"}


async def test_reconfigure_defaults_to_the_current_botanical_name(
    hass: HomeAssistant,
) -> None:
    """The search field opens prefilled with the plant's current botanical name."""
    entry = await _entry_with(
        hass,
        [_row("Hydrangea", [_SPRING], species="paniculata")],
        plants=[_plant("Hydrangea", "paniculata", "Mine")],
    )
    subentry_id = next(iter(entry.subentries))

    result = await _reconfigure(hass, entry, subentry_id)
    field = next(f for f in result["data_schema"].schema if f == "query")
    assert field.default() == "Hydrangea paniculata"
