"""Tests for StayFit coordinator failure handling."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.stayfit.api import (
    StayFitAuthenticationError,
    StayFitConnectionError,
)
from custom_components.stayfit.coordinator import StayFitDataUpdateCoordinator


async def test_authentication_failure_requests_reauth(hass: HomeAssistant) -> None:
    """A rejected token is promoted to Home Assistant reauthentication."""
    client = AsyncMock()
    client.async_get_memberships.side_effect = StayFitAuthenticationError
    coordinator = StayFitDataUpdateCoordinator(hass, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_temporary_failure_preserves_previous_data(hass: HomeAssistant) -> None:
    """A transient cloud failure keeps cached data and marks refresh failed."""
    client = AsyncMock()
    client.async_get_memberships.return_value = ()
    coordinator = StayFitDataUpdateCoordinator(hass, client)
    await coordinator.async_refresh()
    original_data = coordinator.data

    client.async_get_memberships.side_effect = StayFitConnectionError
    await coordinator.async_refresh()

    assert coordinator.data is original_data
    assert coordinator.last_update_success is False


async def test_update_method_wraps_connection_error(hass: HomeAssistant) -> None:
    """Direct update failures use the coordinator's expected exception type."""
    client = AsyncMock()
    client.async_get_memberships.side_effect = StayFitConnectionError
    coordinator = StayFitDataUpdateCoordinator(hass, client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
