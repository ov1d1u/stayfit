"""Tests for StayFit account actions, eligibility, and entity updates."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stayfit.api import (
    StayFitApiClient,
    StayFitApiError,
    StayFitAuthenticationError,
    StayFitConnectionError,
    StayFitInvalidResponseError,
    StayFitRateLimitError,
    StayFitTimeoutError,
)
from custom_components.stayfit.const import DOMAIN
from custom_components.stayfit.models import parse_memberships
from custom_components.stayfit.services import (
    _get_freeze,
    _validate_freeze,
)

TODAY = date(2026, 10, 23)
MEMBERSHIP = {
    "mmid": "10",
    "membership_name": "Gold",
    "date_start": "2026-01-01",
    "date_end": "2026-12-31",
    "flag_status": "1",
    "max_freeze_period": "30",
    "total_freeze": "0",
    "freeze_use_times": "2",
    "count_freeze": "0",
    "freeze_add_interval": "0",
    "recurrent": "0",
}
ACTIVE_FREEZE = {
    "mmfid": "20",
    "date_start": "2026-10-20",
    "date_end": "2026-10-30",
    "days": "10",
    "can_stop": "1",
}


@pytest.fixture
async def account_factory(hass: HomeAssistant, freezer):
    """Create independent loaded accounts backed entirely by mocks."""
    freezer.move_to("2026-10-23T10:00:00Z")

    async def create(member_id="123", memberships=None):
        parsed = parse_memberships(
            [deepcopy(MEMBERSHIP)] if memberships is None else memberships
        )
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=member_id,
            title=f"Member {member_id}",
            data={
                "member_id": member_id,
                "display_name": f"Member {member_id}",
                "token": f"token-{member_id}",
                "username": f"{member_id}@example.com",
            },
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.stayfit.api.StayFitApiClient.async_get_memberships",
            AsyncMock(return_value=parsed),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        client = AsyncMock(spec=StayFitApiClient)
        client.async_get_memberships.return_value = parsed
        entry.runtime_data.coordinator.client = client
        return entry, client

    return create


async def _call(hass, entry, service="freeze_subscription", **data: Any):
    await hass.services.async_call(
        DOMAIN,
        service,
        {"config_entry_id": entry.entry_id, **data},
        blocking=True,
    )


def _state(hass, entry, suffix):
    registry = er.async_get(hass)
    entity = next(
        item
        for item in registry.entities.values()
        if item.config_entry_id == entry.entry_id and item.unique_id.endswith(suffix)
    )
    return hass.states.get(entity.entity_id)


async def test_freeze_refreshes_before_write_and_updates_entities(
    hass: HomeAssistant, account_factory
) -> None:
    """Default actions use real primary IDs and publish confirmed cloud state."""
    entry, client = await account_factory()
    updated = {
        **MEMBERSHIP,
        "date_end": "2027-01-07",
        "total_freeze": "7",
        "freeze": ACTIVE_FREEZE,
    }
    client.async_get_memberships.side_effect = [
        parse_memberships([MEMBERSHIP]),
        parse_memberships([updated]),
    ]

    await _call(hass, entry, days=7)

    client.async_freeze_subscription.assert_awaited_once_with("10", TODAY, 7)
    assert client.async_get_memberships.await_count == 2
    assert _state(hass, entry, "active_subscription_freeze").state == "on"
    assert _state(hass, entry, "subscription_expire_date").state == "2027-01-07"
    assert _state(hass, entry, "available_freeze_days").state == "23"
    assert (
        _state(hass, entry, "subscription_type").attributes["subscription_id"] == "10"
    )
    freeze = _state(hass, entry, "active_subscription_freeze").attributes["freezes"][0]
    assert freeze == {
        "freeze_id": "20",
        "date_start": "2026-10-20",
        "date_end": "2026-10-30",
        "days": 10,
        "can_stop": True,
    }


async def test_explicit_subscription_is_confined_to_account(
    hass: HomeAssistant, account_factory
) -> None:
    """An override selects another plan without writing to another account."""
    other = {**MEMBERSHIP, "mmid": "11", "date_end": "2026-11-30"}
    entry, client = await account_factory(memberships=[MEMBERSHIP, other])
    second, second_client = await account_factory("456")

    await _call(hass, entry, days=3, subscription_id="11", start_date="2026-11-01")

    client.async_freeze_subscription.assert_awaited_once_with(
        "11", date(2026, 11, 1), 3
    )
    second_client.async_freeze_subscription.assert_not_awaited()
    with pytest.raises(ServiceValidationError) as error:
        await _call(hass, second, days=3, subscription_id="11")
    assert error.value.translation_key == "subscription_not_found"


async def test_unfreeze_active_and_refresh(
    hass: HomeAssistant, account_factory
) -> None:
    """Automatic unfreezing stops the active permitted freeze and refreshes."""
    frozen = {**MEMBERSHIP, "total_freeze": "10", "freeze": ACTIVE_FREEZE}
    entry, client = await account_factory(memberships=[frozen])
    assert _state(hass, entry, "available_freeze_days").state == "20"
    client.async_get_memberships.side_effect = [
        parse_memberships([frozen]),
        parse_memberships([MEMBERSHIP]),
    ]

    await _call(hass, entry, "unfreeze_subscription")

    client.async_unfreeze_subscription.assert_awaited_once_with("20")
    assert _state(hass, entry, "active_subscription_freeze").state == "off"
    assert _state(hass, entry, "available_freeze_days").state == "30"


async def test_explicit_scheduled_freeze(hass: HomeAssistant, account_factory) -> None:
    """Only an explicit freeze ID can stop a future scheduled freeze."""
    scheduled = {**ACTIVE_FREEZE, "date_start": "2026-11-01", "date_end": "2026-11-11"}
    entry, client = await account_factory(
        memberships=[{**MEMBERSHIP, "freeze": scheduled}]
    )
    with pytest.raises(ServiceValidationError) as error:
        await _call(hass, entry, "unfreeze_subscription")
    assert error.value.translation_key == "freeze_not_stoppable"

    await _call(hass, entry, "unfreeze_subscription", freeze_id="20")
    client.async_unfreeze_subscription.assert_awaited_once_with("20")


@pytest.mark.parametrize("days", [0, -1, True, 1.5, "3"])
async def test_invalid_day_schema(hass: HomeAssistant, account_factory, days) -> None:
    """Invalid counts are rejected before any eligibility request or write."""
    entry, client = await account_factory()
    with pytest.raises(vol.Invalid):
        await _call(hass, entry, days=days)
    client.async_get_memberships.assert_not_awaited()
    client.async_freeze_subscription.assert_not_awaited()


@pytest.mark.parametrize(
    ("changes", "start", "days", "error_key"),
    [
        ({"max_freeze_period": "3"}, TODAY, 4, "freeze_days_exceeded"),
        ({"total_freeze": "30"}, TODAY, 1, "freeze_days_exceeded"),
        ({"count_freeze": "2"}, TODAY, 1, "freeze_uses_exhausted"),
        ({"count_freeze": "3"}, TODAY, 1, "freeze_uses_exhausted"),
        ({"freeze_add_interval": "-2"}, TODAY, 1, "invalid_start_date"),
        ({"freeze_add_interval": "2"}, date(2026, 10, 20), 1, "invalid_start_date"),
        ({"recurrent": "1"}, date(2026, 10, 24), 1, "recurring_start_date"),
        ({}, date(2025, 12, 31), 1, "invalid_start_date"),
        ({}, date(2027, 1, 1), 1, "invalid_start_date"),
        ({"date_end": "invalid"}, TODAY, 1, "invalid_membership_dates"),
        ({"max_freeze_period": None}, TODAY, 1, "eligibility_unknown"),
        ({"total_freeze": "invalid"}, TODAY, 1, "eligibility_unknown"),
        ({"recurrent": None}, TODAY, 1, "eligibility_unknown"),
        ({"freeze_add_interval": None}, TODAY, 1, "eligibility_unknown"),
        ({"freeze": ACTIVE_FREEZE}, TODAY, 1, "overlapping_freeze"),
        (
            {"freeze": {**ACTIVE_FREEZE, "date_end": None}},
            TODAY,
            1,
            "eligibility_unknown",
        ),
    ],
)
def test_freeze_validation(changes, start, days, error_key) -> None:
    """Enforce cloud rules before sending a subscription write."""
    membership = parse_memberships([{**MEMBERSHIP, **changes}])[0]
    with pytest.raises(ServiceValidationError) as error:
        _validate_freeze(membership, start, days, TODAY)
    assert error.value.translation_key == error_key


@pytest.mark.parametrize(
    ("changes", "start"),
    [
        ({"freeze_use_times": "0", "count_freeze": None}, TODAY),
        ({"freeze_add_interval": "-2"}, date(2026, 10, 25)),
        ({"freeze_add_interval": "2"}, date(2026, 10, 21)),
        ({"recurrent": "1", "freeze_add_interval": None}, TODAY),
        ({"freeze": {**ACTIVE_FREEZE, "days": "0"}}, TODAY),
        ({"freeze": ACTIVE_FREEZE}, date(2026, 10, 30)),
        ({"freeze_add_interval": "0"}, date(2026, 1, 1)),
    ],
)
def test_permitted_freeze_boundaries(changes, start) -> None:
    """Respect unlimited uses, allowed dates, cancellation, and exclusive ends."""
    membership = parse_memberships([{**MEMBERSHIP, **changes}])[0]
    _validate_freeze(membership, start, 1, TODAY)


@pytest.mark.parametrize(
    ("freezes", "freeze_id", "error_key"),
    [
        ([{**ACTIVE_FREEZE, "can_stop": "0"}], None, "freeze_not_stoppable"),
        ([{**ACTIVE_FREEZE, "days": "0"}], "20", "freeze_not_stoppable"),
        ([{**ACTIVE_FREEZE, "date_end": "2026-10-23"}], "20", "freeze_not_stoppable"),
        ([{**ACTIVE_FREEZE, "mmfid": None}], None, "missing_freeze_id"),
        ([ACTIVE_FREEZE], "other-subscription-freeze", "freeze_not_found"),
        ([ACTIVE_FREEZE, {**ACTIVE_FREEZE, "mmfid": "21"}], None, "ambiguous_freeze"),
    ],
)
def test_unfreeze_validation(freezes, freeze_id, error_key) -> None:
    """Only one genuine, permitted freeze can be stopped."""
    membership = parse_memberships([{**MEMBERSHIP, "freeze": freezes}])[0]
    with pytest.raises(ServiceValidationError) as error:
        _get_freeze(membership, freeze_id, TODAY)
    assert error.value.translation_key == error_key


async def test_invalid_target_entries(hass: HomeAssistant) -> None:
    """Actions remain registered even when accounts are unloaded or missing."""
    assert await async_setup_component(hass, DOMAIN, {})
    other = MockConfigEntry(domain="other", data={})
    other.add_to_hass(hass)
    unloaded = MockConfigEntry(domain=DOMAIN, data={})
    unloaded.add_to_hass(hass)
    for entry_id, key in [
        ("missing", "entry_not_found"),
        (other.entry_id, "entry_not_found"),
        (unloaded.entry_id, "entry_not_loaded"),
    ]:
        with pytest.raises(ServiceValidationError) as error:
            await hass.services.async_call(
                DOMAIN,
                "freeze_subscription",
                {"config_entry_id": entry_id, "days": 1},
                blocking=True,
            )
        assert error.value.translation_key == key


@pytest.mark.parametrize(
    ("memberships", "error_key"),
    [
        ([], "subscription_not_found"),
        ([{**MEMBERSHIP, "mmid": None}], "missing_subscription_id"),
    ],
)
async def test_missing_membership_ids(
    hass: HomeAssistant, account_factory, memberships, error_key
) -> None:
    """No mutation is possible using synthetic parser fallback IDs."""
    entry, client = await account_factory(memberships=memberships)
    with pytest.raises(ServiceValidationError) as error:
        await _call(hass, entry, days=1)
    assert error.value.translation_key == error_key
    client.async_freeze_subscription.assert_not_awaited()


@pytest.mark.parametrize(
    ("exception", "key"),
    [
        (StayFitConnectionError(), "refresh_failed"),
        (StayFitAuthenticationError(), "auth_required"),
    ],
)
async def test_failed_preread_prevents_write(
    hass: HomeAssistant, account_factory, exception, key
) -> None:
    """Never write based on stale eligibility, including after auth failure."""
    entry, client = await account_factory()
    client.async_get_memberships.side_effect = exception
    with pytest.raises(HomeAssistantError) as error:
        await _call(hass, entry, days=1)
    assert error.value.translation_key == key
    client.async_freeze_subscription.assert_not_awaited()


@pytest.mark.parametrize(
    ("exception", "key"),
    [
        (StayFitApiError("ERROR_FREEZE_PERIOD_OVERLAPS"), "api_rejected"),
        (StayFitAuthenticationError(), "auth_required"),
        (StayFitRateLimitError(), "action_rate_limited"),
        (StayFitTimeoutError(), "write_uncertain"),
        (StayFitInvalidResponseError(), "write_uncertain"),
    ],
)
async def test_write_failures_are_never_retried(
    hass: HomeAssistant, account_factory, exception, key
) -> None:
    """Report backend/auth/uncertain outcomes without repeating mutations."""
    entry, client = await account_factory()
    client.async_freeze_subscription.side_effect = exception
    with pytest.raises(HomeAssistantError) as error:
        await _call(hass, entry, days=1)
    assert error.value.translation_key == key
    assert client.async_freeze_subscription.await_count == 1
    if key == "auth_required":
        assert any(
            flow["context"]["source"] == config_entries.SOURCE_REAUTH
            for flow in hass.config_entries.flow.async_progress()
        )


async def test_confirmed_write_with_failed_refresh(
    hass: HomeAssistant, account_factory
) -> None:
    """A successful write followed by a failed read has a distinct message."""
    entry, client = await account_factory()
    client.async_get_memberships.side_effect = [
        parse_memberships([MEMBERSHIP]),
        StayFitConnectionError(),
    ]
    with pytest.raises(HomeAssistantError) as error:
        await _call(hass, entry, days=1)
    assert error.value.translation_key == "refresh_after_write_failed"
    client.async_freeze_subscription.assert_awaited_once()


async def test_unload_preserves_action_registration(
    hass: HomeAssistant, account_factory
) -> None:
    """Unloading one account does not remove another account's actions."""
    first, _ = await account_factory()
    second, client = await account_factory("456")
    assert await hass.config_entries.async_unload(first.entry_id)
    assert hass.services.has_service(DOMAIN, "freeze_subscription")
    await _call(hass, second, days=1)
    client.async_freeze_subscription.assert_awaited_once()


async def test_same_account_serialization(hass: HomeAssistant, account_factory) -> None:
    """Concurrent actions revalidate in order, preventing duplicate freezes."""
    entry, client = await account_factory()
    started, finish = asyncio.Event(), asyncio.Event()

    async def write(*args: Any):
        started.set()
        await finish.wait()
        client.async_get_memberships.return_value = parse_memberships(
            [{**MEMBERSHIP, "freeze": ACTIVE_FREEZE}]
        )

    client.async_freeze_subscription.side_effect = write
    first = asyncio.create_task(_call(hass, entry, days=1))
    await started.wait()
    second = asyncio.create_task(_call(hass, entry, days=1))
    try:
        await asyncio.sleep(0)
        assert client.async_get_memberships.await_count == 1
    finally:
        finish.set()
    await first
    with pytest.raises(ServiceValidationError) as error:
        await second
    assert error.value.translation_key == "overlapping_freeze"
    assert client.async_freeze_subscription.await_count == 1


async def test_local_today_default(
    hass: HomeAssistant, account_factory, freezer
) -> None:
    """Default dates follow Home Assistant's zone rather than the UTC date."""
    entry, client = await account_factory()
    await hass.config.async_set_time_zone("Europe/Bucharest")
    freezer.move_to("2026-10-23T22:30:00Z")
    await _call(hass, entry, days=1)
    client.async_freeze_subscription.assert_awaited_once_with(
        "10", date(2026, 10, 24), 1
    )


async def test_actions_have_valid_descriptions_and_translations(
    hass: HomeAssistant,
) -> None:
    """Home Assistant can load action selectors and localized descriptions."""
    assert await async_setup_component(hass, DOMAIN, {})
    descriptions = (await async_get_all_descriptions(hass))[DOMAIN]
    assert set(descriptions) == {"freeze_subscription", "unfreeze_subscription"}
    freeze_fields = descriptions["freeze_subscription"]["fields"]
    assert freeze_fields["config_entry_id"]["required"] is True
    assert freeze_fields["config_entry_id"]["selector"] == {
        "config_entry": {"integration": DOMAIN}
    }
    assert freeze_fields["days"]["required"] is True
    assert "date" in freeze_fields["start_date"]["selector"]
    translated = await async_get_translations(hass, "en", "services", {DOMAIN})
    assert translated["component.stayfit.services.freeze_subscription.name"] == (
        "Freeze subscription"
    )
    errors = await async_get_translations(hass, "en", "exceptions", {DOMAIN})
    assert "component.stayfit.exceptions.write_uncertain.message" in errors


async def test_other_account_not_blocked_by_pending_write(
    hass: HomeAssistant, account_factory
) -> None:
    """A slow change for one member never serializes a different member."""
    entry, client = await account_factory()
    second_entry, second_client = await account_factory("456")
    started, finish = asyncio.Event(), asyncio.Event()

    async def write(*args: Any):
        started.set()
        await finish.wait()

    client.async_freeze_subscription.side_effect = write
    first = asyncio.create_task(_call(hass, entry, days=1))
    await started.wait()
    try:
        await _call(hass, second_entry, days=1)
        second_client.async_freeze_subscription.assert_awaited_once()
        assert not first.done()
    finally:
        finish.set()
        await first


async def test_cross_subscription_freeze_id_rejected(
    hass: HomeAssistant, account_factory
) -> None:
    """A freeze ID must belong to the explicitly selected subscription."""
    another = {**MEMBERSHIP, "mmid": "11", "freeze": ACTIVE_FREEZE}
    entry, client = await account_factory(memberships=[MEMBERSHIP, another])
    with pytest.raises(ServiceValidationError) as error:
        await _call(
            hass, entry, "unfreeze_subscription", subscription_id="10", freeze_id="20"
        )
    assert error.value.translation_key == "freeze_not_found"
    client.async_unfreeze_subscription.assert_not_awaited()


async def test_eligibility_is_refreshed_even_after_successful_setup(
    hass: HomeAssistant, account_factory
) -> None:
    """A formerly allowed freeze must be rejected when fresh limits change."""
    entry, client = await account_factory()
    client.async_get_memberships.return_value = parse_memberships(
        [{**MEMBERSHIP, "total_freeze": "30"}]
    )
    with pytest.raises(ServiceValidationError) as error:
        await _call(hass, entry, days=1)
    assert error.value.translation_key == "freeze_days_exceeded"
    client.async_freeze_subscription.assert_not_awaited()
