"""Tests for the browse panel's backend (step 13).

The panel is JavaScript, so what is tested here is the contract it depends on:
two WebSocket commands and the photo proxy. The proxy is exercised with respx so
the suite stays offline.
"""

from __future__ import annotations

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

from custom_components.garden_companion.const import DOMAIN

_HYDRANGEA = "dataset:Hydrangea|paniculata|"
_WISTERIA = "dataset:Wisteria||"
_ROSE_BUSH = "dataset:Rosa||bush"
_JPEG = b"\xff\xd8\xff\xe0panel"


def _plant(genus: str, species: str | None) -> dict[str, Any]:
    """Return stored data for a dataset plant."""
    return {
        "genus": genus,
        "species": species,
        "variant": None,
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
        title="Garden Companion",
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
    """Every row comes back with the fields the grid renders."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants"})
    result = (await client.receive_json())["result"]

    assert result["total"] == 16
    assert len(result["plants"]) == 16
    hydrangea = next(p for p in result["plants"] if p["key"] == _HYDRANGEA)
    assert hydrangea["common"] == "Panicle hydrangea"
    assert hydrangea["botanical"] == "Hydrangea paniculata"
    assert hydrangea["photo"] == f"/api/{DOMAIN}/photo/{_HYDRANGEA}"
    assert hydrangea["credit"] == "Hedwig Storch (CC BY-SA 3.0)"
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
    await _setup(
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
    assert plant["credit"] == "waferboard (CC BY 2.0)"
    assert plant["in_dataset"] is True


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
            "borrow_key": "dataset:Ligustrum||",
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    subentry = next(iter(entry.get_subentries_of_type("plant")))
    assert subentry.data["windows_like"] == {
        "genus": "Ligustrum",
        "species": None,
        "variant": None,
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
            "borrow_key": "dataset:Ligustrum||",
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
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants"})
    plants = (await client.receive_json())["result"]["plants"]

    assert next(p for p in plants if p["key"] == _HYDRANGEA)["added"] == 2
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


async def test_plants_searches_and_reports_the_variant_hint(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A search narrows the list, and a variant row carries its distinguishing text."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "query": "roos"})
    result = (await client.receive_json())["result"]

    keys = {plant["key"] for plant in result["plants"]}
    assert keys == {_ROSE_BUSH, "dataset:Rosa||climber"}
    bush = next(p for p in result["plants"] if p["key"] == _ROSE_BUSH)
    assert bush["distinguish"] == "Stands on its own, not tied to a wall or arch"


async def test_plants_pages_through_the_dataset(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Offset and limit walk the rows without repeats, and total stays the whole set."""
    await _setup(hass)
    client = await hass_ws_client(hass)

    seen: list[str] = []
    for offset in (0, 6, 12):
        await client.send_json_auto_id(
            {"type": f"{DOMAIN}/plants", "limit": 6, "offset": offset}
        )
        result = (await client.receive_json())["result"]
        assert result["total"] == 16
        assert result["offset"] == offset
        seen.extend(plant["key"] for plant in result["plants"])

    assert len(seen) == 16
    assert len(set(seen)) == 16


async def test_plants_past_the_end_is_empty(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """An offset beyond the last row returns nothing, which stops the scrolling."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "offset": 16})
    result = (await client.receive_json())["result"]

    assert result["plants"] == []
    assert result["total"] == 16


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
        {"type": f"{DOMAIN}/add_plant", "key": "dataset:Quercus|robur|"}
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

    response = await client.get(f"/api/{DOMAIN}/photo/dataset:Quercus|robur|")
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


async def test_thumbnail_rewrites_the_width() -> None:
    """A photo URL with a width parameter is asked for at thumbnail size."""
    from custom_components.garden_companion.panel import _thumbnail

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
