"""Load the species dataset off the event loop and hold it on the config entry.

The dataset is static per install, so there is no coordinator and no polling. It
is read once at setup in an executor thread and cached on the entry's runtime
data, where the entities and calendar in later steps read it from.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import _LOGGER
from .models import Species, build_dataset

DATA_FILE = Path(__file__).parent / "data" / "species.yaml"


@dataclass
class GardenCompanionData:
    """Runtime data cached on the config entry."""

    species: list[Species]


type GardenCompanionConfigEntry = ConfigEntry[GardenCompanionData]


def _load(path: Path) -> list[Species]:
    """Read and parse the dataset. Never raises: a bad dataset yields no plants.

    Runs in an executor thread. Parsing a file inside the event loop is the
    classic Home Assistant integration mistake, so this is only ever
    reached through async_add_executor_job. A missing or malformed file must not
    stop the integration from loading, so problems are logged and an empty
    dataset is returned.
    """
    if not path.exists():
        _LOGGER.warning("Species dataset missing at %s; no plants will resolve", path)
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        _LOGGER.exception("Species dataset at %s is not valid YAML", path)
        return []

    species, errors = build_dataset(raw)
    if errors:
        _LOGGER.error(
            "Species dataset at %s has %d problem(s); loading no plants. First: %s",
            path,
            len(errors),
            errors[0],
        )
        return []
    return species


async def async_load_dataset(hass: HomeAssistant) -> list[Species]:
    """Load and parse the dataset in an executor thread."""
    return await hass.async_add_executor_job(_load, DATA_FILE)
