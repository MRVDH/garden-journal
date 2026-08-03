"""Shared fixtures for the Garden Journal test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load this custom integration in every test.

    Without it, HA refuses to load anything from custom_components during tests
    and every entity or config flow test fails with an unhelpful lookup error.
    """
