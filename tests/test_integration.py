"""End-to-end setup tests for StayFit entities."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stayfit.const import (
    CONF_DISPLAY_NAME,
    CONF_MEMBER_ID,
    CONF_TOKEN,
    DOMAIN,
    UPDATE_INTERVAL,
)
from custom_components.stayfit.models import parse_memberships


async def test_setup_creates_exactly_five_entities(hass: HomeAssistant) -> None:
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
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entries = [
        item
        for item in er.async_get(hass).entities.values()
        if item.config_entry_id == entry.entry_id
    ]
    assert len(entries) == 5
    assert {item.unique_id for item in entries} == {
        "123_subscription_active",
        "123_active_subscription_freeze",
        "123_subscription_expire_date",
        "123_subscription_type",
        "123_available_freeze_days",
    }

    states = {item.unique_id: hass.states.get(item.entity_id) for item in entries}
    assert states["123_subscription_active"].state == "on"
    assert states["123_active_subscription_freeze"].state == "on"
    assert states["123_subscription_expire_date"].state == "2026-12-31"
    assert states["123_subscription_type"].state == "Gold"
    assert states["123_available_freeze_days"].state == "11"
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

    with patch(
        "custom_components.stayfit.api.StayFitApiClient.async_get_memberships",
        AsyncMock(return_value=()),
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
    with patch(
        "custom_components.stayfit.api.StayFitApiClient.async_get_memberships",
        AsyncMock(return_value=memberships),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "123_available_freeze_days"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == expected
