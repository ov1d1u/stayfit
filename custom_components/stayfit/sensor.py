"""Sensors for StayFit."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
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
