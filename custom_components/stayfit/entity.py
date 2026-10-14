"""Base entity for StayFit."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import StayFitConfigEntry
from .const import DOMAIN
from .coordinator import StayFitDataUpdateCoordinator


class StayFitEntity(CoordinatorEntity[StayFitDataUpdateCoordinator]):
    """Base class for all StayFit account entities."""

    _attr_has_entity_name = True

    def __init__(self, entry: StayFitConfigEntry, entity_key: str) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._attr_unique_id = f"{entry.runtime_data.member_id}_{entity_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.runtime_data.member_id)},
            name=f"StayFit {entry.runtime_data.display_name}",
            manufacturer="Stay Fit Gym",
            model="Membership account",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://stayfit.ro/",
        )
