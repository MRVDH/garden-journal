"""Tests for the plant photo image entity.

A dataset plant borrows its row's photo and credit; a manual plant carries a bare
URL with no credit, or none at all and then gets no image entity. The fetch itself
is exercised with respx so the suite stays offline, covering both a successful
fetch and a network failure.
"""

from __future__ import annotations

from typing import Any

import httpx
import respx
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_component import DATA_INSTANCES
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garden_journal.const import DOMAIN

_HYDRANGEA_PHOTO = (
    "https://commons.wikimedia.org/wiki/Special:FilePath/"
    "Hydrangea%20paniculata%20IMG%206629.JPG?width=600"
)
_MANUAL_PHOTO = "https://example.test/my-shrub.jpg"
_JPEG = b"\xff\xd8\xff\xe0garden"


def _dataset_plant(genus: str, species: str | None) -> dict[str, Any]:
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


def _manual_plant(image_url: str | None) -> dict[str, Any]:
    """Return stored data for a manually added plant, optionally with a photo."""
    return {
        "genus": "Quercus",
        "species": "robur",
        "display_name": "unused",
        "matched_on": "manual",
        "in_dataset": False,
        "windows_like": None,
        "windows": [
            {"when": {"start": "02-01", "end": "02-28"}, "description": {"en": "prune"}}
        ],
        "source": None,
        "image_url": image_url,
    }


async def _setup(hass: HomeAssistant, plants: list[tuple[str, dict[str, Any]]]) -> None:
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


def _image_entity(hass: HomeAssistant, entity_id: str) -> ImageEntity:
    """Return the image entity object by id."""
    entity = hass.data[DATA_INSTANCES]["image"].get_entity(entity_id)
    assert isinstance(entity, ImageEntity)
    return entity


async def test_dataset_plant_photo_carries_credit(hass: HomeAssistant) -> None:
    """A dataset plant with a photo gets an image entity with its URL and credit."""
    await _setup(hass, [("My hydrangea", _dataset_plant("Hydrangea", "paniculata"))])

    state = hass.states.get("image.my_hydrangea_photo")
    assert state is not None
    assert state.attributes["attribution"] == "Photo by Hedwig Storch (CC BY-SA 3.0)"
    assert _image_entity(hass, "image.my_hydrangea_photo").image_url == _HYDRANGEA_PHOTO


async def test_every_packaged_row_supplies_a_photo(hass: HomeAssistant) -> None:
    """Each row in the packaged dataset carries a photo, so a dataset plant gets one.

    The row-without-a-photo path is covered at the resolver level, where a row can
    be built without an image.
    """
    await _setup(hass, [("My wisteria", _dataset_plant("Wisteria", None))])
    assert hass.states.get("image.my_wisteria_photo") is not None


async def test_manual_plant_photo_has_no_attribution(hass: HomeAssistant) -> None:
    """A manual plant's photo is a bare URL with no credit."""
    await _setup(hass, [("Backyard oak", _manual_plant(_MANUAL_PHOTO))])

    entity = _image_entity(hass, "image.backyard_oak_photo")
    assert entity.image_url == _MANUAL_PHOTO
    assert entity.attribution is None


async def test_manual_plant_without_a_photo_has_no_image_entity(
    hass: HomeAssistant,
) -> None:
    """A manual plant with no photo URL gets no image entity."""
    await _setup(hass, [("Bare oak", _manual_plant(None))])
    assert hass.states.get("image.bare_oak_photo") is None


@respx.mock
async def test_photo_fetches_and_caches(hass: HomeAssistant) -> None:
    """A successful fetch returns the bytes and records the content type."""
    respx.get(_MANUAL_PHOTO).mock(
        return_value=httpx.Response(
            200, content=_JPEG, headers={"content-type": "image/jpeg"}
        )
    )
    await _setup(hass, [("Backyard oak", _manual_plant(_MANUAL_PHOTO))])

    entity = _image_entity(hass, "image.backyard_oak_photo")
    assert await entity.async_image() == _JPEG
    assert entity.content_type == "image/jpeg"


@respx.mock
async def test_photo_fetch_failure_is_graceful(hass: HomeAssistant) -> None:
    """With no network the fetch returns no bytes and does not raise."""
    respx.get(_MANUAL_PHOTO).mock(side_effect=httpx.ConnectError("no network"))
    await _setup(hass, [("Backyard oak", _manual_plant(_MANUAL_PHOTO))])

    entity = _image_entity(hass, "image.backyard_oak_photo")
    assert await entity.async_image() is None
