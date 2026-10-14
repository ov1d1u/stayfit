"""The StayFit integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import StayFitApiClient
from .const import CONF_DISPLAY_NAME, CONF_MEMBER_ID, CONF_TOKEN
from .coordinator import StayFitDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


@dataclass(slots=True)
class StayFitRuntimeData:
    """Runtime data for one StayFit config entry."""

    coordinator: StayFitDataUpdateCoordinator
    member_id: str
    display_name: str


type StayFitConfigEntry = ConfigEntry[StayFitRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: StayFitConfigEntry) -> bool:
    """Set up StayFit from a config entry."""
    client = StayFitApiClient(
        async_get_clientsession(hass), token=entry.data[CONF_TOKEN]
    )
    coordinator = StayFitDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = StayFitRuntimeData(
        coordinator=coordinator,
        member_id=entry.data[CONF_MEMBER_ID],
        display_name=entry.data[CONF_DISPLAY_NAME],
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StayFitConfigEntry) -> bool:
    """Unload a StayFit config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
