"""Shared test fixtures.

Entities register a midnight recompute timer when they are added. Home Assistant
cancels those timers when the config entry is unloaded, which happens on a reload
or on removal in the running app. Tests that set up an entry never remove it, so
this unloads any loaded entry at teardown, letting those timers be cancelled
before the loop is checked for stragglers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


@pytest.fixture(autouse=True)
async def _unload_entries_at_teardown(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[None]:
    """Unload loaded config entries after any test that used Home Assistant."""
    yield
    if "hass" not in request.fixturenames:
        return
    hass: HomeAssistant = request.getfixturevalue("hass")
    await hass.async_block_till_done()
    for entry in hass.config_entries.async_entries():
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
