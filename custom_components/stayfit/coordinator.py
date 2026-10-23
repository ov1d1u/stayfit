"""Data coordinator for StayFit."""

from __future__ import annotations

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
from .models import StayFitCoordinatorData, build_coordinator_data

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
