"""Binary sensors for StayFit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StayFitConfigEntry
from .entity import StayFitEntity
from .models import StayFitCoordinatorData


@dataclass(frozen=True, kw_only=True)
class StayFitBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a StayFit binary sensor."""

    value_fn: Callable[[StayFitCoordinatorData], bool]


BINARY_SENSORS: tuple[StayFitBinarySensorEntityDescription, ...] = (
    StayFitBinarySensorEntityDescription(
        key="subscription_active",
        translation_key="subscription_active",
        value_fn=lambda data: data.subscription_active,
    ),
    StayFitBinarySensorEntityDescription(
        key="active_subscription_freeze",
        translation_key="active_subscription_freeze",
        value_fn=lambda data: data.active_subscription_freeze,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StayFitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StayFit binary sensors."""
    async_add_entities(
        StayFitBinarySensor(entry, description) for description in BINARY_SENSORS
    )


class StayFitBinarySensor(StayFitEntity, BinarySensorEntity):
    """A StayFit binary sensor."""

    entity_description: StayFitBinarySensorEntityDescription

    def __init__(
        self,
        entry: StayFitConfigEntry,
        description: StayFitBinarySensorEntityDescription,
    ) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the binary sensor state."""
        return self.entity_description.value_fn(self.coordinator.data)
