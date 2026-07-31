"""A sidebar panel for browsing the dataset as a grid of photos.

A config flow form cannot render images or a custom layout, so browsing the
dataset with photos needs a frontend of its own. This registers a custom panel,
serves its module from the integration directory, and gives it two WebSocket
commands and a photo proxy.

Search happens on the server and returns a bounded page, so the panel never
depends on the whole dataset fitting in one payload.

Photos are proxied rather than linked directly: the panel fetches them from Home
Assistant, which fetches them from the remote host, so a browser looking at the
grid never contacts Wikimedia and no viewer's IP is exposed (3.7). That is the
same reason the photo entity uses `image_url` rather than `entity_picture`.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import voluptuous as vol
from aiohttp import web
from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.httpx_client import get_async_client

from .config_flow import _default_display_name, _stored_plant, picked_row, row_value
from .const import _LOGGER, DOMAIN
from .dataset import GardenCompanionConfigEntry
from .models import Species
from .resolver import Resolver

_PANEL_URL = f"/{DOMAIN}_panel"
_MODULE_URL = f"{_PANEL_URL}/garden-companion-panel.js"
_COMPONENT = "garden-companion-panel"

# Appended to the module URL so a browser picks up a new build instead of a
# cached one. Bump it when the panel's JavaScript changes.
_MODULE_VERSION = "10"
_PHOTO_URL = f"/api/{DOMAIN}/photo"

# Set once the panel, views and commands are registered, so a config entry
# reload does not register them a second time.
_REGISTERED = f"{DOMAIN}_panel_registered"

# One screenful at a time; the panel asks for the next page as it scrolls.
_DEFAULT_LIMIT = 24
_MAX_LIMIT = 200

# Photo bytes keyed by remote URL, so scrolling the grid does not refetch.
_CACHE_LIMIT = 64

# Wikimedia's robot policy wants a descriptive agent naming the tool and where to
# read about it. Requests carrying one are served happily in parallel, while a
# generic agent is refused with a 429, so this header is what makes the grid work.
_USER_AGENT = (
    "GardenCompanion/0.1.0 (Home Assistant integration; "
    "https://github.com/MRVDH/garden-companion)"
)

# The grid wants thumbnails, not full-size files, and a modest number of
# connections at a time. A refusal is still retried once, in case a host applies
# a limit anyway.
_THUMB_WIDTH = "320"
_MAX_CONCURRENT_FETCHES = 4
_THROTTLED_WAIT = 2.0


def _thumbnail(url: str) -> str:
    """Return the photo URL asking for a grid-sized thumbnail where it can.

    A dataset photo is addressed through Special:FilePath, whose width parameter
    picks a thumbnail. A URL without one is left alone.
    """
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query))
    if "width" not in query:
        return url
    query["width"] = _THUMB_WIDTH
    return urlunparse(parts._replace(query=urlencode(query)))


def _botanical(species: Species) -> str:
    """Return the botanical name, variant included."""
    name = species.genus
    if species.species:
        name += f" {species.species}"
    if species.variant:
        name += f" ({species.variant})"
    return name


def _windows(species: Species, language: str) -> list[dict[str, str]]:
    """Return each pruning window as plain strings, for the detail dialog."""
    return [
        {
            "start": window.start,
            "end": window.end,
            "description": (
                window.description.get(language)
                or window.description.get("en")
                or next(iter(window.description.values()), "")
            ),
        }
        for window in species.windows
    ]


def _as_json(species: Species, language: str, added: int) -> dict[str, Any]:
    """Describe one row for the panel: the card, plus what the dialog shows.

    `added` counts how many plants in the garden come from this row, since the
    same plant can be added more than once under different names.
    """
    return {
        "key": row_value(species),
        "common": _default_display_name(species, language),
        "botanical": _botanical(species),
        "photo": f"{_PHOTO_URL}/{row_value(species)}" if species.image else None,
        "credit": _credit(species),
        "distinguish": (
            species.distinguish.get(language) or species.distinguish.get("en")
            if species.distinguish
            else None
        ),
        "windows": _windows(species, language),
        "source": species.source,
        "added": added,
    }


def _credit(species: Species) -> str | None:
    """Return a photo credit line, or None when the row has no photo."""
    if species.image is None:
        return None
    author = species.image.author
    licence = species.image.licence
    if author and licence:
        return f"{author} ({licence})"
    return author or licence


def _entry(hass: HomeAssistant) -> GardenCompanionConfigEntry | None:
    """Return the config entry while it is loaded, else None.

    The dataset lives on the entry's runtime data, which is only there in the
    loaded state. A reload leaves a short window where there is nothing to read,
    which callers report as `not_loaded` for the panel to retry.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    return None


def _added_counts(entry: GardenCompanionConfigEntry) -> Counter[str]:
    """Count the plants in the garden against the dataset row each came from."""
    counts: Counter[str] = Counter()
    for subentry in entry.get_subentries_of_type("plant"):
        data = subentry.data
        if not data.get("in_dataset", True):
            continue
        parts = (
            data["genus"],
            data.get("species") or "",
            data.get("variant") or "",
        )
        counts["dataset:" + "|".join(parts)] += 1
    return counts


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/plants",
        vol.Optional("query"): str,
        vol.Optional("limit"): vol.All(int, vol.Range(min=1, max=_MAX_LIMIT)),
        vol.Optional("offset"): vol.All(int, vol.Range(min=0)),
    }
)
@callback
def _ws_plants(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one page of dataset rows, filtered by an optional search query.

    The page is bounded and reports the total, so the panel can keep asking for
    the next slice as it scrolls without ever holding the whole dataset.
    """
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_loaded", "Garden Companion is not loaded")
        return
    resolver = Resolver(entry.runtime_data.species)
    query = (msg.get("query") or "").strip()
    rows = resolver.search(query) if query else list(entry.runtime_data.species)
    language = hass.config.language
    rows.sort(key=lambda row: _default_display_name(row, language).casefold())
    offset = msg.get("offset", 0)
    limit = msg.get("limit", _DEFAULT_LIMIT)
    page = rows[offset : offset + limit]
    added = _added_counts(entry)
    connection.send_result(
        msg["id"],
        {
            "total": len(rows),
            "offset": offset,
            "plants": [_as_json(row, language, added[row_value(row)]) for row in page],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/add_plant",
        vol.Required("key"): str,
        vol.Optional("name"): str,
    }
)
@callback
def _ws_add_plant(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a dataset plant, the same stored shape the add flow writes."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_loaded", "Garden Companion is not loaded")
        return
    resolver = Resolver(entry.runtime_data.species)
    row = picked_row(msg["key"], resolver)
    if row is None:
        connection.send_error(
            msg["id"], "unknown_plant", "No such plant in the dataset"
        )
        return
    name = (msg.get("name") or "").strip() or _default_display_name(
        row, hass.config.language
    )
    subentry = ConfigSubentry(
        data=_stored_plant(row, name),
        subentry_type="plant",
        title=name,
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    connection.send_result(msg["id"], {"subentry_id": subentry.subentry_id})


class GardenCompanionPhotoView(HomeAssistantView):
    """Serve a dataset photo, fetched server-side so the browser stays off the host."""

    url = f"{_PHOTO_URL}/{{key}}"
    name = f"api:{DOMAIN}:photo"

    def __init__(self, hass: HomeAssistant) -> None:
        """Keep the caches and the semaphore that bounds outbound fetching."""
        self._hass = hass
        self._memory: dict[str, tuple[str, bytes]] = {}
        self._limit = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)
        self._dir = Path(hass.config.cache_path(DOMAIN))

    async def get(self, request: web.Request, key: str) -> web.Response:
        """Return the photo bytes for one dataset row."""
        entry = _entry(self._hass)
        if entry is None:
            return web.Response(status=503)
        row = picked_row(key, Resolver(entry.runtime_data.species))
        if row is None or row.image is None:
            return web.Response(status=404)
        url = _thumbnail(row.image.url)

        if (cached := self._memory.get(url)) is not None:
            return web.Response(body=cached[1], content_type=cached[0])
        if (
            stored := await self._hass.async_add_executor_job(self._read, url)
        ) is not None:
            self._remember(url, stored)
            return web.Response(body=stored[1], content_type=stored[0])

        async with self._limit:
            # Another request may have filled the cache while this one queued.
            if (cached := self._memory.get(url)) is not None:
                return web.Response(body=cached[1], content_type=cached[0])
            fetched = await self._fetch(url)
        if fetched is None:
            return web.Response(status=502)
        self._remember(url, fetched)
        await self._hass.async_add_executor_job(self._write, url, fetched)
        return web.Response(body=fetched[1], content_type=fetched[0])

    def _remember(self, url: str, photo: tuple[str, bytes]) -> None:
        """Hold a photo in memory, dropping the oldest when full."""
        if len(self._memory) >= _CACHE_LIMIT:
            self._memory.pop(next(iter(self._memory)))
        self._memory[url] = photo

    def _cache_file(self, url: str) -> Path:
        """Return the on-disk name for a photo URL."""
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._dir / f"{digest}.img"

    def _read(self, url: str) -> tuple[str, bytes] | None:
        """Read a cached photo off disk, or None when it is not there."""
        path = self._cache_file(url)
        try:
            body = path.read_bytes()
        except OSError:
            return None
        # The content type is stored on the first line, the bytes after it.
        content_type, _, image = body.partition(b"\n")
        if not image:
            return None
        return content_type.decode("ascii", "replace"), image

    def _write(self, url: str, photo: tuple[str, bytes]) -> None:
        """Cache a photo on disk so a restart does not refetch it."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._cache_file(url).write_bytes(
                photo[0].encode("ascii", "replace") + b"\n" + photo[1]
            )
        except OSError as err:
            _LOGGER.debug("Could not cache photo %s: %s", url, err)

    async def _fetch(self, url: str) -> tuple[str, bytes] | None:
        """Fetch one photo, retrying once if the remote host refuses the rate."""
        client = get_async_client(self._hass)
        for attempt in (1, 2):
            try:
                response = await client.get(
                    url,
                    timeout=20,
                    follow_redirects=True,
                    headers={"User-Agent": _USER_AGENT},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as err:
                throttled = err.response.status_code == HTTPStatus.TOO_MANY_REQUESTS
                if throttled and attempt == 1:
                    await asyncio.sleep(_THROTTLED_WAIT)
                    continue
                _LOGGER.debug("Photo fetch failed for %s: %s", url, err)
                return None
            except httpx.RequestError as err:
                _LOGGER.debug("Photo fetch failed for %s: %s", url, err)
                return None
            content_type = response.headers.get("content-type", "image/jpeg")
            if not content_type.startswith("image/"):
                _LOGGER.debug("Photo at %s is not an image: %s", url, content_type)
                return None
            return content_type, response.content
        return None
        return None


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register the panel, its module, its commands and the photo proxy once."""
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True

    await hass.http.async_register_static_paths(
        [StaticPathConfig(_PANEL_URL, str(Path(__file__).parent / "frontend"), False)]
    )
    hass.http.register_view(GardenCompanionPhotoView(hass))
    websocket_api.async_register_command(hass, _ws_plants)
    websocket_api.async_register_command(hass, _ws_add_plant)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=DOMAIN,
        webcomponent_name=_COMPONENT,
        sidebar_title="Garden Companion",
        sidebar_icon="mdi:content-cut",
        module_url=f"{_MODULE_URL}?v={_MODULE_VERSION}",
        require_admin=True,
    )
