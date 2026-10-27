"""Tests for the pruning reminder blueprint.

The blueprint ships in the repo rather than inside the integration, so these load
it from there and run it as a real automation against the real calendar: the
reminder arrives at the chosen time on the day a window opens, and an excluded
plant stays quiet. Only the phone is a stand-in: a mocked mobile_app device action
platform with the real one's notify schema. The real platform imports camera and
its image libraries, which the test venv does not install.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.blueprint.models import Blueprint, DomainBlueprints
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import template
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util import yaml as yaml_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
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


@pytest.mark.parametrize(("exclude_back", "expected"), [(False, 2), (True, 1)])
async def test_reminder_at_chosen_time_skipping_excluded(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    exclude_back: bool,
    expected: int,
) -> None:
    """Every plant gets a reminder at 09:00 on its opening day, bar the excluded."""
    freezer.move_to(_local(_OPENS - timedelta(hours=12)))

    notify = AsyncMock()
    mock_platform(
        hass,
        "mobile_app.device_action",
        SimpleNamespace(
            ACTION_SCHEMA=cv.DEVICE_ACTION_BASE_SCHEMA.extend(
                {
                    vol.Required("type"): "notify",
                    vol.Required("message"): cv.template,
                    vol.Optional("title"): cv.template,
                    vol.Optional("data"): cv.template_complex,
                }
            ),
            async_call_action_from_config=notify,
        ),
    )

    phone_entry = MockConfigEntry(domain="mobile_app")
    phone_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    phone = devices.async_get_or_create(
        config_entry_id=phone_entry.entry_id, identifiers={("mobile_app", "phone")}
    )

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
                            "notify_device": phone.id,
                            "exclude_plants": [back.id] if exclude_back else [],
                        },
                    }
                }
            },
        )
        await hass.async_block_till_done()

        # Midnight opens the window, but the reminder waits for the time of day.
        await _advance(hass, freezer, _local(_OPENS + timedelta(hours=8, minutes=55)))
        assert notify.call_count == 0

        await _advance(hass, freezer, _local(_OPENS + timedelta(hours=9, minutes=10)))
        assert notify.call_count == expected

        # Detaches the calendar trigger, whose polling timer would outlive the test.
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": "all"}, blocking=True
        )

    sent = []
    for call in notify.call_args_list:
        _hass, config, variables, _context = call.args
        assert config["device_id"] == phone.id
        sent.append(template.render_complex(config["title"], variables))
        assert "five leaves" in template.render_complex(config["message"], variables)
    assert sorted(sent) == (
        ["Prune Front"] if exclude_back else ["Prune Back", "Prune Front"]
    )
