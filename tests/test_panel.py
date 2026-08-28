"""Tests for the browse panel's backend.

The panel is JavaScript, so what is tested here is the contract it depends on:
two WebSocket commands and the photo proxy. The proxy is exercised with respx so
the suite stays offline.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import respx
from freezegun import freeze_time
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.garden_journal.const import DOMAIN
from custom_components.garden_journal.panel import _MAX_LIMIT

_HYDRANGEA = "dataset:Hydrangea|paniculata"
_WISTERIA = "dataset:Wisteria|"
_JPEG = b"\xff\xd8\xff\xe0panel"


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
    hass: HomeAssistant, plants: list[tuple[str, dict[str, Any]]] | None = None
) -> MockConfigEntry:
    """Set up the integration, optionally with plants already added.

    The photo cache lives on disk under the config directory, which the test
    harness shares between tests and between runs, so it is emptied here to give
    each test a cold cache.
    """
    shutil.rmtree(hass.config.cache_path(DOMAIN), ignore_errors=True)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Journal",
        subentries_data=[
            ConfigSubentryData(
                subentry_type="plant", title=title, data=data, unique_id=None
            )
            for title, data in (plants or [])
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_plants_lists_the_dataset(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Every row comes back with the fields the grid renders.

    The row count is read from the answer rather than written down, so growing the
    dataset does not break the test.
    """
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "limit": _MAX_LIMIT})
    result = (await client.receive_json())["result"]

    assert result["total"] > 1
    assert len(result["plants"]) == result["total"]
    hydrangea = next(p for p in result["plants"] if p["key"] == _HYDRANGEA)
    assert hydrangea["common"] == "Panicle hydrangea"
    assert hydrangea["botanical"] == "Hydrangea paniculata"
    assert hydrangea["photo"] == f"/api/{DOMAIN}/photo/{_HYDRANGEA}"
    # Composed from the row's author and licence, whichever photo it carries.
    assert re.fullmatch(r".+ \(.+\)", hydrangea["credit"])
    assert hydrangea["added"] == 0
    # The dialog shows the windows and the source, so the card payload carries them.
    assert hydrangea["source"].startswith("https://groei.nl/")
    assert len(hydrangea["windows"]) == 1
    window = hydrangea["windows"][0]
    assert (window["start"], window["end"]) == ("03-01", "04-15")
    assert "framework" in window["description"]


async def test_garden_lists_your_plants_urgent_first(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """The garden view puts an open window first, then the soonest date."""
    entry = await _setup(
        hass,
        [
            ("By the shed", _plant("Hydrangea", "paniculata")),
            ("The wisteria", _plant("Wisteria", None)),
        ],
    )
    # The connection is made against the real clock, which its token check needs.
    client = await hass_ws_client(hass)
    with freeze_time("2026-08-01"):
        await client.send_json_auto_id({"type": f"{DOMAIN}/garden"})
        plants = (await client.receive_json())["result"]["plants"]

    # Wisteria prunes mid-July to end of August, so on 1 August it is open.
    assert [p["name"] for p in plants] == ["The wisteria", "By the shed"]
    wisteria, hydrangea = plants
    assert wisteria["prune_now"] is True
    assert wisteria["next"] == "2026-07-15"
    assert wisteria["end"] == "2026-08-31"
    assert wisteria["botanical"] == "Wisteria"
    assert wisteria["advice"]
    assert wisteria["image_entity"] == "image.the_wisteria_photo"
    # The thumbnail goes through the cached photo proxy, keyed by subentry.
    wisteria_subentry = next(
        s for s in entry.get_subentries_of_type("plant") if s.title == "The wisteria"
    )
    assert (
        wisteria["photo"]
        == f"/api/{DOMAIN}/plant_photo/{wisteria_subentry.subentry_id}"
    )
    assert wisteria["needs_attention"] is False
    assert hydrangea["prune_now"] is False
    assert hydrangea["next"] == "2027-03-01"


async def test_garden_flags_a_plant_that_needs_attention(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A plant whose key resolves to nothing is flagged with no date."""
    await _setup(hass, [("Backyard oak", _plant("Quercus", "robur"))])
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/garden"})
    plants = (await client.receive_json())["result"]["plants"]

    assert len(plants) == 1
    assert plants[0]["needs_attention"] is True
    assert plants[0]["next"] is None
    assert plants[0]["advice"] is None


async def test_garden_is_empty_without_plants(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """With nothing added the garden is empty rather than an error."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/garden"})
    result = (await client.receive_json())["result"]

    assert result["plants"] == []


async def test_garden_carries_what_the_dialog_shows(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A plant comes with every window, its source and its photo credit."""
    await _setup(hass, [("The wisteria", _plant("Wisteria", None))])
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/garden"})
    plant = (await client.receive_json())["result"]["plants"][0]

    assert len(plant["windows"]) == 2
    assert plant["source"].startswith("https://groei.nl/")
    assert re.fullmatch(r".+ \(.+\)", plant["credit"])
    assert plant["in_dataset"] is True
    # Wisteria has nothing to do continuously, which is the common case.
    assert plant["care"] == []
    assert plant["care_now"] is False


async def test_garden_carries_continuous_care_and_whether_it_is_open(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A plant with care carries its season and, in season, that it applies now."""
    await _setup(hass, [("The rose", _plant("Rosa", None))])
    # The connection is made against the real clock, which its token check needs.
    client = await hass_ws_client(hass)
    with freeze_time("2026-08-01"):
        await client.send_json_auto_id({"type": f"{DOMAIN}/garden"})
        plant = (await client.receive_json())["result"]["plants"][0]

    assert len(plant["care"]) == 1
    assert plant["care"][0]["start"] == "06-01"
    assert plant["care"][0]["description"]
    assert plant["care_now"] is True
    # The end of the open season, so the row can show "until <date>" like pruning.
    assert plant["care_end"] == "2026-10-15"
    # The pruning window is closed in August, so care is the only job open.
    assert plant["prune_now"] is False


async def test_add_manual_plant_with_its_own_windows(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A plant outside the dataset can be added with windows written by hand."""
    entry = await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/add_manual_plant",
            "name": "Buxus bij de deur",
            "botanical": "Buxus sempervirens",
            "windows": [
                {"start": "05-15", "end": "06-15", "description": "Scheer de haag"}
            ],
            "source": "https://example.test/buxus",
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    subentry = next(iter(entry.get_subentries_of_type("plant")))
    assert subentry.title == "Buxus bij de deur"
    assert subentry.data["in_dataset"] is False
    assert subentry.data["genus"] == "Buxus"
    assert subentry.data["species"] == "sempervirens"
    assert subentry.data["source"] == "https://example.test/buxus"
    assert subentry.data["windows"] == [
        {
            "when": {"start": "05-15", "end": "06-15"},
            "description": {hass.config.language: "Scheer de haag"},
        }
    ]
    assert hass.states.get("sensor.buxus_bij_de_deur_next_pruning") is not None


async def test_add_manual_plant_borrowing_timing(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A manual plant can take the timing of a plant pruned the same way."""
    entry = await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/add_manual_plant",
            "name": "De taxus",
            "botanical": "Taxus baccata",
            "borrow_key": "dataset:Ligustrum|",
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    subentry = next(iter(entry.get_subentries_of_type("plant")))
    assert subentry.data["windows_like"] == {
        "genus": "Ligustrum",
        "species": None,
    }
    # The borrowed timing drives the sensor, so it has a date.
    state = hass.states.get("sensor.de_taxus_next_pruning")
    assert state is not None
    assert state.state not in ("unknown", "unavailable")


async def test_add_manual_plant_rejects_an_impossible_date(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """31 February is refused, the same rule the dataset is held to."""
    entry = await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/add_manual_plant",
            "name": "Nope",
            "botanical": "Quercus robur",
            "windows": [{"start": "02-31", "end": "03-01", "description": "Snoei"}],
        }
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "invalid_date"
    assert not entry.get_subentries_of_type("plant")


async def test_add_manual_plant_needs_one_kind_of_timing(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Neither borrowing nor writing the timing is refused, and so is both."""
    await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/add_manual_plant",
            "name": "Nope",
            "botanical": "Quercus robur",
        }
    )
    assert (await client.receive_json())["error"]["code"] == "invalid_timing"

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/add_manual_plant",
            "name": "Nope",
            "botanical": "Quercus robur",
            "borrow_key": "dataset:Ligustrum|",
            "windows": [{"start": "05-01", "end": "05-31", "description": "Snoei"}],
        }
    )
    assert (await client.receive_json())["error"]["code"] == "invalid_timing"


async def test_adding_a_plant_raises_no_notification(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Adding a plant by hand goes through quietly, with nothing to dismiss."""
    await _setup(hass)
    client = await hass_ws_client(hass)

    with patch(
        "homeassistant.components.persistent_notification.async_create"
    ) as notify:
        await client.send_json_auto_id(
            {
                "type": f"{DOMAIN}/add_manual_plant",
                "name": "Buxus bij de deur",
                "botanical": "Buxus sempervirens",
                "windows": [
                    {"start": "05-15", "end": "06-15", "description": "Scheer de haag"}
                ],
            }
        )
        assert (await client.receive_json())["success"]
        await hass.async_block_till_done()

    assert not notify.called


async def test_rename_plant_changes_the_title(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Renaming updates the subentry title and its stored display name."""
    entry = await _setup(hass, [("By the shed", _plant("Hydrangea", "paniculata"))])
    subentry_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/rename_plant",
            "subentry_id": subentry_id,
            "name": "  Naast de schuur  ",
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    subentry = entry.subentries[subentry_id]
    assert subentry.title == "Naast de schuur"
    assert subentry.data["display_name"] == "Naast de schuur"


async def test_rename_plant_rejects_an_empty_name(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A blank name is refused rather than leaving a nameless plant."""
    entry = await _setup(hass, [("By the shed", _plant("Hydrangea", "paniculata"))])
    subentry_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/rename_plant", "subentry_id": subentry_id, "name": "   "}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert entry.subentries[subentry_id].title == "By the shed"


async def test_remove_plant_takes_its_entities_with_it(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Removing a plant drops the subentry and its entities."""
    entry = await _setup(hass, [("By the shed", _plant("Hydrangea", "paniculata"))])
    subentry_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)
    assert hass.states.get("sensor.by_the_shed_next_pruning") is not None

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/remove_plant", "subentry_id": subentry_id}
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    assert not entry.get_subentries_of_type("plant")
    assert hass.states.get("sensor.by_the_shed_next_pruning") is None


async def test_remove_plant_rejects_an_unknown_id(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """An id naming no plant is refused rather than erroring out of the handler."""
    await _setup(hass, [("By the shed", _plant("Hydrangea", "paniculata"))])
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/remove_plant", "subentry_id": "nope"}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "unknown_plant"


async def test_plants_counts_what_is_already_added(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Each row reports how many plants in the garden came from it."""
    await _setup(
        hass,
        [
            ("By the shed", _plant("Hydrangea", "paniculata")),
            ("By the door", _plant("Hydrangea", "paniculata")),
        ],
    )
    client = await hass_ws_client(hass)

    # Queried by name rather than read off the first page, so the assertion does
    # not depend on where these two rows fall once the dataset grows.
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "query": "hortensia"})
    plants = (await client.receive_json())["result"]["plants"]
    assert next(p for p in plants if p["key"] == _HYDRANGEA)["added"] == 2

    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "query": "wisteria"})
    plants = (await client.receive_json())["result"]["plants"]
    assert next(p for p in plants if p["key"] == _WISTERIA)["added"] == 0


async def test_plants_ignores_manual_plants_in_the_count(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A manually added plant is not counted against a dataset row."""
    manual = _plant("Hydrangea", "paniculata") | {"in_dataset": False}
    await _setup(hass, [("Something else", manual)])
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants"})
    plants = (await client.receive_json())["result"]["plants"]

    assert next(p for p in plants if p["key"] == _HYDRANGEA)["added"] == 0


async def test_plants_searches_by_a_common_name(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A Dutch common name narrows the list to the rows that answer to it."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "query": "hortensia"})
    result = (await client.receive_json())["result"]

    keys = {plant["key"] for plant in result["plants"]}
    assert keys == {
        _HYDRANGEA,
        "dataset:Hydrangea|arborescens",
        "dataset:Hydrangea|macrophylla",
        "dataset:Hydrangea|aspera",
    }
    assert result["total"] == 4


async def test_a_row_names_itself_in_the_users_language() -> None:
    """A card carries the common name for the language, falling back to English."""
    from custom_components.garden_journal.models import Species
    from custom_components.garden_journal.panel import _as_json

    row = Species(
        genus="Rosa",
        species=None,
        names={"en": ["Rose"], "nl": ["Roos"]},
        windows=(),
        source="https://example.test",
    )

    assert _as_json(row, "nl", 0)["common"] == "Roos"
    assert _as_json(row, "en", 0)["common"] == "Rose"
    assert _as_json(row, "de", 0)["common"] == "Rose"
    assert _as_json(row, "nl", 0)["botanical"] == "Rosa"
    assert _as_json(row, "nl", 0)["key"] == "dataset:Rosa|"


async def test_a_card_carries_care_in_the_users_language() -> None:
    """Care reaches the dialog with its season and localised advice."""
    from custom_components.garden_journal.models import Care, Species
    from custom_components.garden_journal.panel import _as_json

    row = Species(
        genus="Rosa",
        species=None,
        names={"en": ["Rose"], "nl": ["Roos"]},
        windows=(),
        source="https://example.test",
        care=(
            Care(
                start="06-01",
                end="10-15",
                description={"en": "Deadhead.", "nl": "Knip bloemen weg."},
            ),
        ),
    )

    assert _as_json(row, "nl", 0)["care"] == [
        {"start": "06-01", "end": "10-15", "description": "Knip bloemen weg."}
    ]
    assert _as_json(row, "de", 0)["care"][0]["description"] == "Deadhead."


async def test_plants_pages_through_the_dataset(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Offset and limit walk the rows without repeats, and total stays the whole set."""
    await _setup(hass)
    client = await hass_ws_client(hass)

    page = 5
    seen: list[str] = []
    total = None
    offset = 0
    while total is None or offset < total:
        await client.send_json_auto_id(
            {"type": f"{DOMAIN}/plants", "limit": page, "offset": offset}
        )
        result = (await client.receive_json())["result"]
        total = result["total"]
        assert result["offset"] == offset
        seen.extend(plant["key"] for plant in result["plants"])
        offset += page

    assert len(seen) == total
    assert len(set(seen)) == total


async def test_plants_past_the_end_is_empty(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """An offset beyond the last row returns nothing, which stops the scrolling."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants"})
    total = (await client.receive_json())["result"]["total"]

    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "offset": total})
    result = (await client.receive_json())["result"]

    assert result["plants"] == []
    assert result["total"] == total


async def test_add_plant_creates_the_plant_and_its_entities(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Adding from the panel creates the subentry and its entities."""
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/add_plant", "key": _HYDRANGEA, "name": "By the shed"}
    )
    response = await client.receive_json()
    assert response["success"]
    await hass.async_block_till_done()

    titles = [s.title for s in entry.get_subentries_of_type("plant")]
    assert titles == ["By the shed"]
    assert hass.states.get("sensor.by_the_shed_next_pruning") is not None
    assert hass.states.get("image.by_the_shed_photo") is not None


async def test_a_regular_user_can_add_a_plant(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """A non-admin can manage the garden, not only view it.

    The panel and its commands were admin-only; managing the plant list is a
    shared household task, so a regular user drives it too. This connects as a
    read-only user and adds a plant.
    """
    entry = await _setup(hass)
    client = await hass_ws_client(access_token=hass_read_only_access_token)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/add_plant", "key": _HYDRANGEA, "name": "Hers"}
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    assert [s.title for s in entry.get_subentries_of_type("plant")] == ["Hers"]


async def test_add_plant_defaults_the_name(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """With no name given, the plant is named after its common name."""
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/add_plant", "key": _WISTERIA})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    assert [s.title for s in entry.get_subentries_of_type("plant")] == ["Wisteria"]


async def test_add_plant_rejects_an_unknown_key(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A key naming no row is refused rather than creating a broken plant."""
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/add_plant", "key": "dataset:Quercus|robur"}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "unknown_plant"
    assert not entry.get_subentries_of_type("plant")


@respx.mock
async def test_photo_proxy_serves_the_image(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """The proxy fetches the photo server-side and serves the bytes on."""
    route = respx.get(url__startswith="https://commons.wikimedia.org").mock(
        return_value=httpx.Response(
            200, content=_JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    await _setup(hass)
    client = await hass_client()

    response = await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    assert response.status == 200
    assert response.content_type == "image/jpeg"
    assert await response.read() == _JPEG
    assert route.called


@respx.mock
async def test_plant_photo_proxy_serves_a_garden_plant(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A garden plant's photo is served, and cached, by its subentry.

    The garden thumbnail uses this route rather than the image entity's
    rotating-token URL, which carries no cache headers and refetches on every
    reload. Same cache and immutable headers as the dataset route.
    """
    route = respx.get(url__startswith="https://commons.wikimedia.org").mock(
        return_value=httpx.Response(
            200, content=_JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    entry = await _setup(hass, [("The wisteria", _plant("Wisteria", None))])
    subentry_id = next(iter(entry.get_subentries_of_type("plant"))).subentry_id
    client = await hass_client()

    response = await client.get(f"/api/{DOMAIN}/plant_photo/{subentry_id}")
    assert response.status == 200
    assert response.content_type == "image/jpeg"
    assert await response.read() == _JPEG
    cache_control = response.headers["Cache-Control"]
    assert "immutable" in cache_control
    assert "max-age=" in cache_control
    assert response.headers["ETag"]
    assert route.called


async def test_plant_photo_proxy_unknown_plant_is_not_found(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A subentry that is not in the garden is a 404, not a crash."""
    await _setup(hass)
    client = await hass_client()

    response = await client.get(f"/api/{DOMAIN}/plant_photo/nope")
    assert response.status == 404


@respx.mock
async def test_photo_proxy_lets_the_browser_cache(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """The response carries cache headers, so the browser holds the photo itself.

    Without these the browser refetches every photo through the proxy on each
    visit to the grid, which is slow and reads as the photos not caching.
    """
    respx.get(url__startswith="https://commons.wikimedia.org").mock(
        return_value=httpx.Response(
            200, content=_JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    await _setup(hass)
    client = await hass_client()

    response = await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    assert response.status == 200
    cache_control = response.headers["Cache-Control"]
    assert "immutable" in cache_control
    assert "max-age=" in cache_control
    assert response.headers["ETag"]


@respx.mock
async def test_photo_proxy_answers_a_conditional_request_with_304(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A browser holding the photo revalidates for free: matching ETag gets a 304."""
    route = respx.get(url__startswith="https://commons.wikimedia.org").mock(
        return_value=httpx.Response(
            200, content=_JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    await _setup(hass)
    client = await hass_client()

    first = await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    etag = first.headers["ETag"]

    again = await client.get(
        f"/api/{DOMAIN}/photo/{_HYDRANGEA}", headers={"If-None-Match": etag}
    )
    assert again.status == 304
    assert await again.read() == b""
    # The conditional request is answered from the key alone, without a fetch.
    assert route.call_count == 1


@respx.mock
async def test_photo_proxy_caches(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A second request for the same photo does not refetch it."""
    route = respx.get(url__startswith="https://commons.wikimedia.org").mock(
        return_value=httpx.Response(
            200, content=_JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    await _setup(hass)
    client = await hass_client()

    await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    assert route.call_count == 1


@respx.mock
async def test_photo_proxy_caches_on_disk(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A cached photo survives a restart, so the remote host is asked once."""
    route = respx.get(url__startswith="https://commons.wikimedia.org").mock(
        return_value=httpx.Response(
            200, content=_JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    entry = await _setup(hass)
    client = await hass_client()
    await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    assert route.call_count == 1

    cached = await hass.async_add_executor_job(
        lambda: list(Path(hass.config.cache_path(DOMAIN)).glob("*.img"))
    )
    assert len(cached) == 1

    # A reload builds a fresh view, so its memory cache starts empty.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    response = await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")

    assert response.status == 200
    assert await response.read() == _JPEG
    assert route.call_count == 1


async def test_photo_proxy_unknown_plant_is_not_found(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A key naming no row returns not found rather than reaching the network."""
    await _setup(hass)
    client = await hass_client()

    response = await client.get(f"/api/{DOMAIN}/photo/dataset:Quercus|robur")
    assert response.status == 404


async def test_plants_reports_not_loaded_while_unloaded(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """With the entry unloaded the command says so, which the panel waits out."""
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    await client.send_json_auto_id({"type": f"{DOMAIN}/plants"})
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "not_loaded"


async def test_credit_joins_author_and_licence() -> None:
    """A credit reads "author (licence)", and falls back to whichever is there."""
    from custom_components.garden_journal.models import Image, Species
    from custom_components.garden_journal.panel import _credit

    def row(**image: str) -> Species:
        return Species(
            genus="Test",
            species=None,
            names={"en": ["Test"]},
            windows=(),
            source="https://example.test",
            image=Image(url="https://example.test/x.jpg", **image) if image else None,
        )

    assert _credit(row(author="A. Photographer", licence="CC BY-SA 4.0")) == (
        "A. Photographer (CC BY-SA 4.0)"
    )
    assert _credit(row(author="A. Photographer")) == "A. Photographer"
    assert _credit(row(licence="CC0")) == "CC0"
    assert _credit(row()) is None


async def test_thumbnail_rewrites_the_width() -> None:
    """A photo URL with a width parameter is asked for at thumbnail size."""
    from custom_components.garden_journal.panel import _thumbnail

    assert _thumbnail("https://x.test/a.jpg?width=600") == (
        "https://x.test/a.jpg?width=320"
    )
    assert _thumbnail("https://x.test/a.jpg") == "https://x.test/a.jpg"


@respx.mock
async def test_photo_proxy_retries_once_when_throttled(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A rate-limited fetch is retried, so a busy remote host is survivable."""
    route = respx.get(url__startswith="https://commons.wikimedia.org").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"}),
        ]
    )
    await _setup(hass)
    client = await hass_client()

    response = await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    assert response.status == 200
    assert await response.read() == _JPEG
    assert route.call_count == 2


@respx.mock
async def test_photo_proxy_reports_a_failed_fetch(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A photo that cannot be fetched is a bad gateway, not a crash."""
    respx.get(url__startswith="https://commons.wikimedia.org").mock(
        side_effect=httpx.ConnectError("no network")
    )
    await _setup(hass)
    client = await hass_client()

    response = await client.get(f"/api/{DOMAIN}/photo/{_HYDRANGEA}")
    assert response.status == 502
