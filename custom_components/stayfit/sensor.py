"""Sensors for StayFit."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
            StayFitLastGymCheckInSensor(entry),
            StayFitCheckInsLast30DaysSensor(entry),
            StayFitNextRecurringPaymentDateSensor(entry),
            StayFitActivePenaltiesSensor(entry),
            StayFitPenaltiesRemainingSensor(entry),
            StayFitUnreadAppMessagesSensor(entry),
            StayFitGuestPassVouchersAvailableSensor(entry),
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


class StayFitLastGymCheckInSensor(StayFitEntity, SensorEntity):
    """The account's latest gym check-in."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_gym_checkin"
    _attr_icon = "mdi:map-marker-check"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(
            entry,
            "last_gym_checkin",
            coordinator=entry.runtime_data.activity_coordinator,
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the latest check-in timestamp."""
        data = self.coordinator.data
        checkin = data.latest_checkin if data else None
        return checkin.checked_in_at if checkin else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the gym that recorded the check-in."""
        data = self.coordinator.data
        checkin = data.latest_checkin if data else None
        return {"club": checkin.club if checkin else None}


class StayFitCheckInsLast30DaysSensor(StayFitEntity, SensorEntity):
    """The number of gym check-ins in the rolling 30-day window."""

    _attr_native_unit_of_measurement = "check-ins"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "checkins_last_30_days"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(
            entry,
            "checkins_last_30_days",
            coordinator=entry.runtime_data.activity_coordinator,
        )

    @property
    def native_value(self) -> int | None:
        """Return the rolling check-in count."""
        data = self.coordinator.data
        value = data.checkins_last_30_days if data else None
        return value if value is not None and value >= 0 else None


class StayFitNextRecurringPaymentDateSensor(StayFitEntity, SensorEntity):
    """The primary membership's next recurring payment date."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "next_recurring_payment_date"
    _attr_icon = "mdi:credit-card-clock"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(entry, "next_recurring_payment_date")

    @property
    def native_value(self) -> date | None:
        """Return the next payment date for a recurring membership."""
        primary = self.coordinator.data.primary
        if primary is None or primary.recurrent is not True:
            return None
        return primary.next_payment_date


class StayFitActivePenaltiesSensor(StayFitEntity, SensorEntity):
    """The primary membership's active booking penalties."""

    _attr_native_unit_of_measurement = "penalties"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "active_penalties"
    _attr_icon = "mdi:alert-circle"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(entry, "active_penalties")

    @property
    def native_value(self) -> int | None:
        """Return the active penalty count."""
        primary = self.coordinator.data.primary
        if (
            primary is None
            or primary.total_penalties is None
            or primary.total_penalties < 0
        ):
            return None
        return primary.total_penalties


class StayFitPenaltiesRemainingSensor(StayFitEntity, SensorEntity):
    """The primary membership's remaining penalty allowance."""

    _attr_native_unit_of_measurement = "penalties"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "penalties_remaining"
    _attr_icon = "mdi:alert-decagram-outline"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(entry, "penalties_remaining")

    @property
    def native_value(self) -> int | None:
        """Return the number of penalties before the membership limit."""
        primary = self.coordinator.data.primary
        if (
            primary is None
            or primary.total_penalties is None
            or primary.penalty_limit is None
            or primary.total_penalties < 0
            or primary.penalty_limit < 0
        ):
            return None
        return max(0, primary.penalty_limit - primary.total_penalties)


class StayFitUnreadAppMessagesSensor(StayFitEntity, SensorEntity):
    """The number of unread messages in the official app inbox."""

    _attr_native_unit_of_measurement = "messages"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "unread_app_messages"
    _attr_icon = "mdi:email-outline"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(
            entry,
            "unread_app_messages",
            coordinator=entry.runtime_data.activity_coordinator,
        )

    @property
    def native_value(self) -> int | None:
        """Return the unread inbox count."""
        data = self.coordinator.data
        value = data.unread_messages if data else None
        return value if value is not None and value >= 0 else None


class StayFitGuestPassVouchersAvailableSensor(StayFitEntity, SensorEntity):
    """The primary membership's available guest-pass vouchers."""

    _attr_native_unit_of_measurement = "vouchers"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "guest_pass_vouchers_available"
    _attr_icon = "mdi:ticket-account"

    def __init__(self, entry: StayFitConfigEntry) -> None:
        super().__init__(entry, "guest_pass_vouchers_available")

    @property
    def native_value(self) -> int | None:
        """Return the available guest-pass voucher count."""
        primary = self.coordinator.data.primary
        if (
            primary is None
            or primary.slots_available is None
            or primary.slots_available < 0
        ):
            return None
        return primary.slots_available
