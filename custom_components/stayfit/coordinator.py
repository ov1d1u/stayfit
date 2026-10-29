"""Data coordinator for StayFit."""

from __future__ import annotations

import asyncio
import logging
from asyncio import Lock

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    StayFitApiClient,
    StayFitApiError,
    StayFitAuthenticationError,
    StayFitConnectionError,
    StayFitInvalidResponseError,
    StayFitRateLimitError,
)
from .const import DOMAIN, UPDATE_INTERVAL
from .models import (
    StayFitActivityData,
    StayFitCoordinatorData,
    build_activity_data,
    build_coordinator_data,
)

_LOGGER = logging.getLogger(__name__)


class StayFitDataUpdateCoordinator(DataUpdateCoordinator[StayFitCoordinatorData]):
    """Coordinate polling of one StayFit account."""

    def __init__(self, hass: HomeAssistant, client: StayFitApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.action_lock = Lock()

    async def _async_update_data(self) -> StayFitCoordinatorData:
        try:
            memberships = await self.client.async_get_memberships()
        except StayFitAuthenticationError as err:
            raise ConfigEntryAuthFailed("StayFit authentication expired") from err
        except (
            StayFitApiError,
            StayFitConnectionError,
            StayFitInvalidResponseError,
            StayFitRateLimitError,
        ) as err:
            raise UpdateFailed(f"Unable to update StayFit data: {err}") from err

        return build_coordinator_data(memberships, dt_util.now().date())


class StayFitActivityDataUpdateCoordinator(DataUpdateCoordinator[StayFitActivityData]):
    """Coordinate account activity and inbox polling."""

    def __init__(
        self, hass: HomeAssistant, client: StayFitApiClient, member_id: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_activity",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.member_id = member_id

    async def _async_update_data(self) -> StayFitActivityData:
        try:
            dashboard, latest_checkin = await asyncio.gather(
                self.client.async_get_dashboard(self.member_id),
                self.client.async_get_latest_checkin(),
            )
        except StayFitAuthenticationError as err:
            raise ConfigEntryAuthFailed("StayFit authentication expired") from err
        except (
            StayFitApiError,
            StayFitConnectionError,
            StayFitInvalidResponseError,
            StayFitRateLimitError,
        ) as err:
            raise UpdateFailed(
                f"Unable to update StayFit activity data: {err}"
            ) from err

        return build_activity_data(dashboard, latest_checkin)
