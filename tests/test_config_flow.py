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

from custom_components.garden_companion.config_flow import _snippet
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


async def test_the_first_step_lists_every_dataset_row(hass: HomeAssistant) -> None:
    """The picker offers every row, labelled so variants of one genus differ."""
    entry = await _entry_with(
        hass,
        [
            _row(
                "Hydrangea",
                [_SPRING],
                species="paniculata",
                names={"nl": ["Pluimhortensia"], "en": ["Panicle hydrangea"]},
            ),
            _row(
                "Rosa",
                [_APRIL],
                variant="bush",
                names={"nl": ["Roos"], "en": ["Rose"]},
                distinguish={"nl": "Staat op zichzelf", "en": "Stands on its own"},
            ),
            _row(
                "Rosa",
                [_SUMMER],
                variant="climber",
                names={"nl": ["Klimroos"], "en": ["Climbing rose"]},
                distinguish={"nl": "Tegen een muur", "en": "Trained against a wall"},
            ),
        ],
    )
    result = await _start(hass, entry)

    field = next(f for f in result["data_schema"].schema if f == "query")
    options = result["data_schema"].schema[field].config["options"]
    labels = [option["label"] for option in options]
    assert labels == [
        "Climbing rose (Rosa), Trained against a wall",
        "Panicle hydrangea (Hydrangea paniculata)",
        "Rose (Rosa), Stands on its own",
    ]


async def test_picking_from_the_list_skips_the_search(hass: HomeAssistant) -> None:
    """Choosing an option names that exact row, with no disambiguation."""
    entry = await _entry_with(
        hass,
        [
            _row("Hydrangea", [_SPRING], species="paniculata"),
            _row("Hydrangea", [_APRIL], species="macrophylla"),
        ],
    )
    result = await _start(hass, entry)
    options = result["data_schema"].schema["query"].config["options"]
    macrophylla = next(o for o in options if "macrophylla" in o["label"])

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": macrophylla["value"]}
    )
    assert result["step_id"] == "name"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"display_name": "By the door"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["species"] == "macrophylla"


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


async def _reach_author(hass: HomeAssistant) -> dict[str, Any]:
    """Drive the flow to the first authored-window form."""
    entry = await _entry_with(hass, [_row("Wisteria", [_SUMMER])])
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "Quercus"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"botanical": "Quercus robur", "display_name": "Oak"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "author"}
    )
    assert result["step_id"] == "window"
    return result


async def test_author_two_windows_creates_a_plant(hass: HomeAssistant) -> None:
    """Authoring two windows stores them with matched_on manual and no windows_like."""
    result = await _reach_author(hass)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "start_month": "7",
            "start_day": 15,
            "end_month": "8",
            "end_day": 31,
            "description": "Shorten side shoots",
        },
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "window_menu"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "window"}
    )
    assert result["step_id"] == "window"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "start_month": "1",
            "start_day": 15,
            "end_month": "2",
            "end_day": 15,
            "description": "Cut back to spurs",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "details"}
    )
    assert result["step_id"] == "details"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data["matched_on"] == "manual"
    assert data["in_dataset"] is False
    assert data["windows_like"] is None
    assert [w["when"] for w in data["windows"]] == [
        {"start": "07-15", "end": "08-31"},
        {"start": "01-15", "end": "02-15"},
    ]
    assert data["source"] is None


async def test_author_rejects_an_impossible_date(hass: HomeAssistant) -> None:
    """31 February is refused with an error, staying on the window form."""
    result = await _reach_author(hass)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "start_month": "2",
            "start_day": 31,
            "end_month": "3",
            "end_day": 1,
            "description": "x",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "window"
    assert result["errors"] == {"base": "invalid_date"}


def test_snippet_renders_a_paste_ready_row() -> None:
    """The contribution snippet has the genus, names, source and window."""
    snippet = _snippet(
        "Buxus",
        "sempervirens",
        "Box hedge",
        "en",
        [{"when": {"start": "07-15", "end": "08-31"}, "description": {"en": "Trim"}}],
        None,
    )
    assert "- genus: Buxus" in snippet
    assert "species: sempervirens" in snippet
    assert "en: [Box hedge]" in snippet
    assert "nl: [TODO]" in snippet
    assert "source: TODO" in snippet
    assert 'when: { start: "07-15", end: "08-31" }' in snippet
    assert "en: Trim" in snippet


async def _add_plant(
    hass: HomeAssistant,
    entry: ConfigEntry,
    query: str,
    choice: str | None = None,
    display: str = "Plant",
) -> str:
    """Add a plant through the flow and return its new subentry id."""
    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": query}
    )
    if choice is not None:
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"choice": choice}
        )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"display_name": display}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return next(iter(entry.subentries))


async def test_reconfigure_repicks_the_species(hass: HomeAssistant) -> None:
    """Reconfigure re-maps a dataset plant to a different species, keeping its name."""
    entry = await _entry_with(
        hass,
        [
            _row("Hydrangea", [_SPRING], species="paniculata"),
            _row("Hydrangea", [_APRIL], species="macrophylla"),
        ],
    )
    subentry_id = await _add_plant(hass, entry, "hydrangea", choice="0", display="Mine")
    assert entry.subentries[subentry_id].data["species"] == "paniculata"

    # The entry's runtime data holds the packaged dataset; inject the ambiguous
    # one so re-picking has more than one species to choose between.
    species, _ = build_dataset(
        [
            _row("Hydrangea", [_SPRING], species="paniculata"),
            _row("Hydrangea", [_APRIL], species="macrophylla"),
        ]
    )
    entry.runtime_data = GardenCompanionData(species=species)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "plant"),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
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


async def test_reconfigure_no_match_shows_error(hass: HomeAssistant) -> None:
    """Reconfigure with a name not in the dataset re-shows the step with an error."""
    entry = await _entry_with(
        hass, [_row("Hydrangea", [_SPRING], species="paniculata")]
    )
    subentry_id = await _add_plant(hass, entry, "hydrangea")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "plant"),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "quercus"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "not_found"}
