"""Tests for the pruning reminder blueprint.

The blueprint ships in the repo rather than inside the integration, so these load
it from there and run it as a real automation against the real calendar: the
reminder arrives at the chosen time on the day a window opens, and an excluded
plant stays quiet. Only the phones are stand-ins: a mocked mobile_app integration
whose notify entities record what they are sent. The real integration imports
camera and its image libraries, which the test venv does not install.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.blueprint.models import Blueprint, DomainBlueprints
from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigSubentryData
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util import yaml as yaml_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    async_fire_time_changed,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.garden_journal.const import DOMAIN

_BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation"
_PATH = "garden_journal/notify_pruning_start.yaml"

# Wisteria's summer window opens on 15 July.
_OPENS = datetime(2026, 7, 15)


def _wisteria() -> dict[str, Any]:
    """Return stored data for a dataset Wisteria."""
    return {
        "genus": "Wisteria",
        "species": None,
        "display_name": "unused",
        "matched_on": "genus",
        "in_dataset": True,
        "windows_like": None,
        "windows": None,
        "source": None,
        "image_url": None,
    }


def _load_from_repo(self: DomainBlueprints, blueprint_path: str) -> Blueprint:
    """Load a blueprint from the repo instead of the instance's config folder."""
    return Blueprint(
        yaml_util.load_yaml_dict(_BLUEPRINTS / blueprint_path),
        expected_domain=self.domain,
        path=blueprint_path,
        schema=self._blueprint_schema,
    )


def _local(moment: datetime) -> datetime:
    """Attach the instance's time zone to a naive local time."""
    return moment.replace(tzinfo=dt_util.get_default_time_zone())


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, until: datetime
) -> None:
    """Step the clock forward a few minutes at a time, so the trigger's polling keeps up."""
    now = dt_util.now()
    while now < until:
        now = min(now + timedelta(minutes=5), until)
        freezer.move_to(now)
        async_fire_time_changed(hass, now)
        await hass.async_block_till_done()


class _Phone(NotifyEntity):
    """A phone's notify entity, as the mobile_app integration creates one."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, name: str, sent: list[tuple[str, str | None, str]]) -> None:
        """Belong to the phone's device and record into `sent`."""
        self._attr_unique_id = name
        self._attr_device_info = DeviceInfo(
            identifiers={("mobile_app", name)}, name=name
        )
        self._sent = sent

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Record the notification instead of pushing it."""
        self._sent.append((self._attr_unique_id, title, message))


async def _add_phones(
    hass: HomeAssistant, names: list[str]
) -> list[tuple[str, str | None, str]]:
    """Set up a mobile_app entry per phone and return what they are sent."""
    sent: list[tuple[str, str | None, str]] = []

    async def setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.NOTIFY])
        return True

    async def setup_notify(
        hass: HomeAssistant,
        entry: ConfigEntry,
        add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        add_entities([_Phone(entry.title, sent)])

    mock_integration(hass, MockModule("mobile_app", async_setup_entry=setup_entry))
    mock_platform(hass, "mobile_app.config_flow")
    mock_platform(
        hass, "mobile_app.notify", MockPlatform(async_setup_entry=setup_notify)
    )
    with mock_config_flow("mobile_app", ConfigFlow):
        for name in names:
            phone = MockConfigEntry(domain="mobile_app", title=name)
            phone.add_to_hass(hass)
            assert await hass.config_entries.async_setup(phone.entry_id)
    await hass.async_block_till_done()
    return sent


@pytest.mark.parametrize("exclude_back", [False, True])
async def test_reminder_at_chosen_time_skipping_excluded(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    exclude_back: bool,
) -> None:
    """Each chosen phone gets every plant's reminder at 09:00, bar the excluded."""
    freezer.move_to(_local(_OPENS - timedelta(hours=12)))

    # The tablet has the app too but is not chosen, so it hears nothing.
    sent = await _add_phones(hass, ["phone", "partner", "tablet"])
    devices = dr.async_get(hass)
    chosen = [
        devices.async_get_device(identifiers={("mobile_app", name)})
        for name in ("phone", "partner")
    ]

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Journal",
        subentries_data=[
            ConfigSubentryData(
                subentry_type="plant", title=title, data=_wisteria(), unique_id=None
            )
            for title in ("Front", "Back")
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    back_id = next(
        sub.subentry_id for sub in entry.subentries.values() if sub.title == "Back"
    )
    back = devices.async_get_device(identifiers={(DOMAIN, back_id)})
    assert back is not None

    with patch.object(DomainBlueprints, "_load_blueprint", _load_from_repo):
        assert await async_setup_component(
            hass,
            "automation",
            {
                "automation": {
                    "use_blueprint": {
                        "path": _PATH,
                        "input": {
                            "notify_device": [device.id for device in chosen],
                            "exclude_plants": [back.id] if exclude_back else [],
                        },
                    }
                }
            },
        )
        await hass.async_block_till_done()

        # Midnight opens the window, but the reminder waits for the time of day.
        await _advance(hass, freezer, _local(_OPENS + timedelta(hours=8, minutes=55)))
        assert sent == []

        await _advance(hass, freezer, _local(_OPENS + timedelta(hours=9, minutes=10)))

        # Detaches the calendar trigger, whose polling timer would outlive the test.
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": "all"}, blocking=True
        )

    plants = ["Front"] if exclude_back else ["Back", "Front"]
    assert sorted((phone, title) for phone, title, _message in sent) == sorted(
        (phone, f"Prune {plant}") for phone in ("phone", "partner") for plant in plants
    )
    assert all("five leaves" in message for _phone, _title, message in sent)
