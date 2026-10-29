"""Tests for StayFit coordinator failure handling."""

from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.stayfit.api import (
    StayFitAuthenticationError,
    StayFitConnectionError,
)
from custom_components.stayfit.coordinator import (
    StayFitActivityDataUpdateCoordinator,
    StayFitDataUpdateCoordinator,
)
from custom_components.stayfit.models import StayFitCheckIn, StayFitDashboardData


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


async def test_activity_update_combines_dashboard_and_checkin(
    hass: HomeAssistant,
) -> None:
    """The activity coordinator publishes both official app responses."""
    client = AsyncMock()
    client.async_get_dashboard.return_value = StayFitDashboardData(6, 2)
    checkin = StayFitCheckIn(
        datetime(2026, 10, 9, 18, 30, tzinfo=ZoneInfo("Europe/Bucharest")),
        "Stay Fit Unirii",
    )
    client.async_get_latest_checkin.return_value = checkin
    coordinator = StayFitActivityDataUpdateCoordinator(hass, client, "123")

    data = await coordinator._async_update_data()

    assert data.checkins_last_30_days == 6
    assert data.unread_messages == 2
    assert data.latest_checkin is checkin
    client.async_get_dashboard.assert_awaited_once_with("123")
    client.async_get_latest_checkin.assert_awaited_once_with()


async def test_activity_authentication_failure_requests_reauth(
    hass: HomeAssistant,
) -> None:
    """An activity endpoint can also reveal an expired account token."""
    client = AsyncMock()
    client.async_get_dashboard.side_effect = StayFitAuthenticationError
    client.async_get_latest_checkin.return_value = None
    coordinator = StayFitActivityDataUpdateCoordinator(hass, client, "123")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
