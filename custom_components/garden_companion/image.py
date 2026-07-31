"""Plant photo: one image entity per plant that has a photo (3.7).

Home Assistant fetches the photo server-side and caches it, so the browser never
contacts the remote host and the photo still renders on a device with no internet
once cached. The photo never changes, so image_last_updated is stamped once at
creation. A fetch that fails serves no bytes and is retried on the next request;
the base class does not mark the entity unavailable, and a missing photo is only
cosmetic (3.9).
"""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .dataset import GardenCompanionConfigEntry
from .entity import plant_device_info
from .models import Image
from .resolver import Resolver, resolve_photo


def _attribution(photo: Image) -> str | None:
    """Return a credit line from whatever the photo carries, or None."""
    if photo.author and photo.licence:
        return f"Photo by {photo.author} ({photo.licence})"
    if photo.author:
        return f"Photo by {photo.author}"
    return photo.licence


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a photo entity for each plant that has one."""
    resolver = Resolver(entry.runtime_data.species)
    for subentry in entry.get_subentries_of_type("plant"):
        photo = resolve_photo(dict(subentry.data), resolver)
        if photo is None:
            continue
        async_add_entities(
            [PlantPhotoImage(hass, subentry.subentry_id, subentry.title, photo)],
            config_subentry_id=subentry.subentry_id,
        )


class PlantPhotoImage(ImageEntity):
    """A plant's photo, fetched and cached by Home Assistant (3.7)."""

    _attr_has_entity_name = True
    _attr_translation_key = "photo"

    def __init__(
        self, hass: HomeAssistant, subentry_id: str, title: str, photo: Image
    ) -> None:
        """Set up the photo entity for one plant."""
        super().__init__(hass)
        self._attr_unique_id = f"{subentry_id}_photo"
        self._attr_device_info = plant_device_info(subentry_id, title)
        self._attr_image_url = photo.url
        self._attr_image_last_updated = dt_util.utcnow()
        self._attr_attribution = _attribution(photo)
