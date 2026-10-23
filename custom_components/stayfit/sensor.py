"""Sensors for StayFit."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StayFitConfigEntry
from .entity import StayFitEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StayFitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StayFit sensors."""
    async_add_entities(
        (
            StayFitSubscriptionExpireDateSensor(entry),
            StayFitSubscriptionTypeSensor(entry),
            StayFitAvailableFreezeDaysSensor(entry),
        )
    )


class StayFitSubscriptionExpireDateSensor(StayFitEntity, SensorEntity):
    """The primary membership expiration date."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "subscription_expire_date"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(entry, "subscription_expire_date")

    @property
    def native_value(self) -> date | None:
        """Return the membership end date."""
        primary = self.coordinator.data.primary
        return primary.date_end if primary else None


class StayFitSubscriptionTypeSensor(StayFitEntity, SensorEntity):
    """The primary membership type."""

    _attr_translation_key = "subscription_type"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(entry, "subscription_type")

    @property
    def native_value(self) -> str | None:
        """Return the membership name."""
        primary = self.coordinator.data.primary
        return primary.name if primary else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Expose the API identifier used by subscription actions."""
        primary = self.coordinator.data.primary
        return {"subscription_id": primary.api_membership_id if primary else None}


class StayFitAvailableFreezeDaysSensor(StayFitEntity, SensorEntity):
    """The primary subscription's remaining freeze-day allowance."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_suggested_display_precision = 0
    _attr_translation_key = "available_freeze_days"
    _attr_icon = "mdi:snowflake"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(entry, "available_freeze_days")

    @property
    def native_value(self) -> int | None:
        """Return unused days, or unknown when StayFit omits valid counters."""
        primary = self.coordinator.data.primary
        if (
            primary is None
            or primary.max_freeze_period is None
            or primary.total_freeze is None
            or primary.max_freeze_period < 0
            or primary.total_freeze < 0
        ):
            return None
        return max(0, primary.max_freeze_period - primary.total_freeze)
