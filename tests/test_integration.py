"""End-to-end setup tests for StayFit entities."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stayfit.api import StayFitConnectionError
from custom_components.stayfit.const import (
    CONF_DISPLAY_NAME,
    CONF_MEMBER_ID,
    CONF_TOKEN,
    DOMAIN,
    UPDATE_INTERVAL,
)
from custom_components.stayfit.models import (
    StayFitCheckIn,
    StayFitDashboardData,
    parse_memberships,
)


async def test_setup_creates_all_entities(hass: HomeAssistant) -> None:
    """Each account creates the requested entities and one service device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Member",
        unique_id="123",
        data={
            "username": "user@example.com",
            CONF_TOKEN: "token",
            CONF_MEMBER_ID: "123",
            CONF_DISPLAY_NAME: "Test Member",
        },
    )
    entry.add_to_hass(hass)
    memberships = parse_memberships(
        [
            {
                "mmid": "9",
                "membership_name": "Gold",
                "date_start": "2026-01-01",
                "date_end": "2026-12-31",
                "flag_status": "1",
                "max_freeze_period": "30",
                "total_freeze": "19",
                "recurrent": "1",
                "next_payment_date": "2026-11-15",
                "total_penalties": "2",
                "penalty_limit": "5",
                "slots_available": "3",
                "freeze": {
                    "date_start": "2026-10-01",
                    "date_end": "2026-10-20",
                    "days": "19",
                },
            }
        ]
    )

    with (
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_memberships",
            AsyncMock(return_value=memberships),
        ),
        patch(
            "custom_components.stayfit.coordinator.dt_util.now",
            return_value=datetime(2026, 10, 9, 12, 0),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_dashboard",
            AsyncMock(return_value=StayFitDashboardData(7, 4)),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_latest_checkin",
            AsyncMock(
                return_value=StayFitCheckIn(
                    datetime(
                        2026,
                        10,
                        8,
                        18,
                        30,
                        tzinfo=ZoneInfo("Europe/Bucharest"),
                    ),
                    "Stay Fit Unirii",
                )
            ),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entries = [
        item
        for item in er.async_get(hass).entities.values()
        if item.config_entry_id == entry.entry_id
    ]
    assert len(entries) == 12
    assert {item.unique_id for item in entries} == {
        "123_subscription_active",
        "123_active_subscription_freeze",
        "123_subscription_expire_date",
        "123_subscription_type",
        "123_available_freeze_days",
        "123_last_gym_checkin",
        "123_checkins_last_30_days",
        "123_next_recurring_payment_date",
        "123_active_penalties",
        "123_penalties_remaining",
        "123_unread_app_messages",
        "123_guest_pass_vouchers_available",
    }

    states = {item.unique_id: hass.states.get(item.entity_id) for item in entries}
    assert states["123_subscription_active"].state == "on"
    assert states["123_active_subscription_freeze"].state == "on"
    assert states["123_subscription_expire_date"].state == "2026-12-31"
    assert states["123_subscription_type"].state == "Gold"
    assert states["123_available_freeze_days"].state == "11"
    assert states["123_last_gym_checkin"].state == "2026-10-08T15:30:00+00:00"
    assert states["123_last_gym_checkin"].attributes["club"] == "Stay Fit Unirii"
    assert states["123_checkins_last_30_days"].state == "7"
    assert states["123_next_recurring_payment_date"].state == "2026-11-15"
    assert states["123_active_penalties"].state == "2"
    assert states["123_penalties_remaining"].state == "3"
    assert states["123_unread_app_messages"].state == "4"
    assert states["123_guest_pass_vouchers_available"].state == "3"
    assert states["123_available_freeze_days"].attributes["unit_of_measurement"] == "d"
    assert states["123_available_freeze_days"].attributes["device_class"] == "duration"
    assert states["123_available_freeze_days"].attributes["friendly_name"] == (
        "StayFit Test Member Available freeze days"
    )
    assert entry.runtime_data.coordinator.update_interval == UPDATE_INTERVAL

    devices = [
        item
        for item in dr.async_get(hass).devices.values()
        if entry.entry_id in item.config_entries
    ]
    assert len(devices) == 1
    assert devices[0].name == "StayFit Test Member"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_empty_memberships_create_false_and_unknown_states(
    hass: HomeAssistant,
) -> None:
    """An account without a subscription remains available and useful."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Empty Member",
        unique_id="456",
        data={
            "username": "empty@example.com",
            CONF_TOKEN: "token",
            CONF_MEMBER_ID: "456",
            CONF_DISPLAY_NAME: "Empty Member",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_memberships",
            AsyncMock(return_value=()),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_dashboard",
            AsyncMock(return_value=StayFitDashboardData(None, None)),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_latest_checkin",
            AsyncMock(return_value=None),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entries = [
        item
        for item in er.async_get(hass).entities.values()
        if item.config_entry_id == entry.entry_id
    ]
    states = {item.unique_id: hass.states.get(item.entity_id) for item in entries}
    assert states["456_subscription_active"].state == "off"
    assert states["456_active_subscription_freeze"].state == "off"
    assert states["456_subscription_expire_date"].state == "unknown"
    assert states["456_subscription_type"].state == "unknown"
    assert states["456_available_freeze_days"].state == "unknown"
    assert states["456_last_gym_checkin"].state == "unknown"
    assert states["456_checkins_last_30_days"].state == "unknown"
    assert states["456_next_recurring_payment_date"].state == "unknown"
    assert states["456_active_penalties"].state == "unknown"
    assert states["456_penalties_remaining"].state == "unknown"
    assert states["456_unread_app_messages"].state == "unknown"
    assert states["456_guest_pass_vouchers_available"].state == "unknown"


async def test_activity_failure_does_not_block_membership_entities(
    hass: HomeAssistant,
) -> None:
    """Optional activity endpoint downtime leaves subscription data usable."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="789",
        data={
            CONF_TOKEN: "token",
            CONF_MEMBER_ID: "789",
            CONF_DISPLAY_NAME: "Membership Only",
        },
    )
    entry.add_to_hass(hass)
    memberships = parse_memberships(
        [
            {
                "mmid": "9",
                "membership_name": "Gold",
                "date_start": "2026-01-01",
                "date_end": "2026-12-31",
                "flag_status": "1",
            }
        ]
    )

    with (
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_memberships",
            AsyncMock(return_value=memberships),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_dashboard",
            AsyncMock(side_effect=StayFitConnectionError),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_latest_checkin",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.stayfit.coordinator.dt_util.now",
            return_value=datetime(2026, 10, 9, 12, 0),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    membership_entity = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "789_subscription_active"
    )
    activity_entity = registry.async_get_entity_id(
        "sensor", DOMAIN, "789_checkins_last_30_days"
    )
    assert membership_entity is not None
    assert activity_entity is not None
    assert hass.states.get(membership_entity).state == "on"
    assert hass.states.get(activity_entity).state == "unavailable"


@pytest.mark.parametrize(
    ("maximum", "used", "expected"),
    [
        (30, 0, "30"),
        (30, 30, "0"),
        (30, 35, "0"),
        (None, 0, "unknown"),
        (30, None, "unknown"),
        ("invalid", 0, "unknown"),
        (30, -1, "unknown"),
        (-1, 0, "unknown"),
    ],
)
async def test_available_freeze_days_data(
    hass: HomeAssistant, maximum, used, expected
) -> None:
    """Distinguish exhausted allowances from missing or malformed API data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="123",
        data={
            CONF_TOKEN: "token",
            CONF_MEMBER_ID: "123",
            CONF_DISPLAY_NAME: "Test Member",
        },
    )
    entry.add_to_hass(hass)
    memberships = parse_memberships(
        [{"mmid": "9", "max_freeze_period": maximum, "total_freeze": used}]
    )
    with (
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_memberships",
            AsyncMock(return_value=memberships),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_dashboard",
            AsyncMock(return_value=StayFitDashboardData(None, None)),
        ),
        patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_latest_checkin",
            AsyncMock(return_value=None),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "123_available_freeze_days"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == expected
