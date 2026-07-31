"""Tests for the browse panel's backend (step 13).

The panel is JavaScript, so what is tested here is the contract it depends on:
two WebSocket commands and the photo proxy. The proxy is exercised with respx so
the suite stays offline.
"""

from __future__ import annotations

from typing import Any

import httpx
import respx
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
    """Set up the integration, optionally with plants already added."""
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
    assert hydrangea["windows"] == [
        {
            "start": "03-01",
            "end": "04-15",
            "description": hydrangea["windows"][0]["description"],
        }
    ]
    assert hydrangea["added"] is False


async def test_plants_marks_what_is_already_added(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A plant already in the garden is flagged so the grid can say so."""
    await _setup(hass, [("By the shed", _plant("Hydrangea", "paniculata"))])
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants"})
    plants = (await client.receive_json())["result"]["plants"]

    assert next(p for p in plants if p["key"] == _HYDRANGEA)["added"] is True
    assert next(p for p in plants if p["key"] == _WISTERIA)["added"] is False


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


async def test_plants_limit_bounds_the_page(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """A limit bounds the page while total still reports the whole match set."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/plants", "limit": 3})
    result = (await client.receive_json())["result"]

    assert result["total"] == 16
    assert len(result["plants"]) == 3


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
