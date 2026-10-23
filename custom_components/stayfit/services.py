"""Account-level actions for freezing and unfreezing StayFit subscriptions."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryAuthFailed, ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import ConfigEntrySelector
from homeassistant.util import dt as dt_util

from .api import (
    StayFitApiError,
    StayFitAuthenticationError,
    StayFitConnectionError,
    StayFitInvalidResponseError,
    StayFitRateLimitError,
)
from .const import DOMAIN
from .models import StayFitFreeze, StayFitMembership

if TYPE_CHECKING:
    from . import StayFitConfigEntry

SERVICE_FREEZE = "freeze_subscription"
SERVICE_UNFREEZE = "unfreeze_subscription"
ATTR_SUBSCRIPTION_ID = "subscription_id"
ATTR_FREEZE_ID = "freeze_id"
ATTR_START_DATE = "start_date"
ATTR_DAYS = "days"


def _positive_days(value: object) -> int:
    """Require a positive whole day count, excluding booleans and fractions."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise vol.Invalid("days must be a positive integer")
    return value


BASE_SCHEMA = {
    vol.Required(ATTR_CONFIG_ENTRY_ID): ConfigEntrySelector({"integration": DOMAIN}),
    vol.Optional(ATTR_SUBSCRIPTION_ID): vol.All(str, vol.Length(min=1)),
}
FREEZE_SCHEMA = vol.Schema(
    {
        **BASE_SCHEMA,
        vol.Required(ATTR_DAYS): _positive_days,
        vol.Optional(ATTR_START_DATE): cv.date,
    }
)
UNFREEZE_SCHEMA = vol.Schema(
    {**BASE_SCHEMA, vol.Optional(ATTR_FREEZE_ID): vol.All(str, vol.Length(min=1))}
)


def _invalid(key: str, **placeholders: str) -> ServiceValidationError:
    """Create a translated action validation error."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
    )


def _failed(key: str) -> HomeAssistantError:
    """Create a translated communication or outcome error."""
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=key)


def _get_entry(hass: HomeAssistant, entry_id: str) -> StayFitConfigEntry:
    """Resolve only loaded StayFit accounts."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise _invalid("entry_not_found")
    if entry.state is not ConfigEntryState.LOADED:
        raise _invalid("entry_not_loaded")
    return cast("StayFitConfigEntry", entry)


def _get_subscription(
    entry: StayFitConfigEntry, subscription_id: str | None
) -> StayFitMembership:
    """Resolve the primary or explicit subscription within this account."""
    data = entry.runtime_data.coordinator.data
    if subscription_id is None:
        membership = data.primary
    else:
        matches = [
            item
            for item in data.memberships
            if item.api_membership_id == subscription_id
        ]
        membership = matches[0] if len(matches) == 1 else None
    if membership is None:
        raise _invalid("subscription_not_found")
    if membership.api_membership_id is None:
        raise _invalid("missing_subscription_id")
    return membership


def _nonnegative(value: int | None, field: str) -> int:
    """Require known, nonnegative eligibility counters."""
    if value is None or value < 0:
        raise _invalid("eligibility_unknown", field=field)
    return value


def _validate_freeze(
    membership: StayFitMembership, start: date, days: int, today: date
) -> None:
    """Enforce the Android app's personal-freeze eligibility rules."""
    if (
        membership.date_start is None
        or membership.date_end is None
        or membership.date_end < membership.date_start
    ):
        raise _invalid("invalid_membership_dates")

    maximum = _nonnegative(membership.max_freeze_period, "max_freeze_period")
    used = _nonnegative(membership.total_freeze, "total_freeze")
    if days > maximum - used:
        raise _invalid("freeze_days_exceeded")
    uses = _nonnegative(membership.freeze_use_times, "freeze_use_times")
    if uses and _nonnegative(membership.count_freeze, "count_freeze") >= uses:
        raise _invalid("freeze_uses_exhausted")

    _validate_start(membership, start, today)
    _validate_overlap(membership.freezes, start, days)


def _validate_start(membership: StayFitMembership, start: date, today: date) -> None:
    """Validate the permitted start-date window using the local calendar."""
    # Date presence and ordering are checked by _validate_freeze first.
    activation = cast("date", membership.date_start)
    expiration = cast("date", membership.date_end)
    if membership.recurrent is None:
        raise _invalid("eligibility_unknown", field="recurrent")
    minimum = activation
    if membership.recurrent:
        if start != today:
            raise _invalid("recurring_start_date")
    else:
        interval = membership.freeze_add_interval
        if interval is None:
            raise _invalid("eligibility_unknown", field="freeze_add_interval")
        if interval:
            try:
                minimum = max(minimum, today - timedelta(days=interval))
            except OverflowError as err:
                raise _invalid(
                    "eligibility_unknown", field="freeze_add_interval"
                ) from err
    if not minimum <= start <= expiration:
        raise _invalid("invalid_start_date")


def _validate_overlap(
    freezes: tuple[StayFitFreeze, ...], start: date, days: int
) -> None:
    """Reject overlap with an existing non-cancelled freeze."""
    try:
        end = start + timedelta(days=days)
    except OverflowError as err:
        raise _invalid("invalid_start_date") from err
    for freeze in freezes:
        if freeze.days == 0:
            continue
        if (
            freeze.days is None
            or freeze.days < 0
            or freeze.date_start is None
            or freeze.date_end is None
            or freeze.date_end <= freeze.date_start
        ):
            raise _invalid("eligibility_unknown", field="freeze")
        if start < freeze.date_end and freeze.date_start < end:
            raise _invalid("overlapping_freeze")


def _get_freeze(
    membership: StayFitMembership, freeze_id: str | None, today: date
) -> StayFitFreeze:
    """Select one active stoppable freeze or a specific scheduled freeze."""
    if freeze_id is not None:
        matches = [item for item in membership.freezes if item.freeze_id == freeze_id]
        if len(matches) != 1:
            raise _invalid("freeze_not_found")
        freeze = matches[0]
        if (
            freeze.days is None
            or freeze.days <= 0
            or freeze.date_start is None
            or freeze.date_end is None
            or freeze.date_end <= max(today, freeze.date_start)
            or not freeze.can_stop
        ):
            raise _invalid("freeze_not_stoppable")
        return freeze

    candidates = [
        item for item in membership.freezes if item.is_active(today) and item.can_stop
    ]
    if not candidates:
        raise _invalid("freeze_not_stoppable")
    if len(candidates) > 1:
        raise _invalid("ambiguous_freeze")
    if candidates[0].freeze_id is None:
        raise _invalid("missing_freeze_id")
    return candidates[0]


async def _refresh(entry: StayFitConfigEntry, *, after_write: bool = False) -> None:
    """Refresh without debounce and distinguish a completed write from a read error."""
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_refresh()
    if coordinator.last_update_success:
        return
    if isinstance(coordinator.last_exception, ConfigEntryAuthFailed):
        entry.async_start_reauth(coordinator.hass)
        if not after_write:
            raise _invalid("auth_required")
    raise _failed("refresh_after_write_failed" if after_write else "refresh_failed")


async def _handle_action(hass: HomeAssistant, call: ServiceCall) -> None:
    """Refresh, validate and execute exactly one write for a single account."""
    entry = _get_entry(hass, call.data[ATTR_CONFIG_ENTRY_ID])
    coordinator = entry.runtime_data.coordinator
    async with coordinator.action_lock:
        _get_entry(hass, entry.entry_id)
        await _refresh(entry)
        _get_entry(hass, entry.entry_id)
        membership = _get_subscription(entry, call.data.get(ATTR_SUBSCRIPTION_ID))
        today = dt_util.now().date()
        freeze = None
        start = call.data.get(ATTR_START_DATE, today)
        if call.service == SERVICE_FREEZE:
            _validate_freeze(membership, start, call.data[ATTR_DAYS], today)
        else:
            freeze = _get_freeze(membership, call.data.get(ATTR_FREEZE_ID), today)

        try:
            if freeze is None:
                await coordinator.client.async_freeze_subscription(
                    cast("str", membership.api_membership_id),
                    start,
                    call.data[ATTR_DAYS],
                )
            else:
                await coordinator.client.async_unfreeze_subscription(
                    cast("str", freeze.freeze_id)
                )
        except StayFitAuthenticationError as err:
            entry.async_start_reauth(hass)
            raise _invalid("auth_required") from err
        except StayFitApiError as err:
            raise _invalid("api_rejected", reason=err.code) from err
        except StayFitRateLimitError as err:
            raise _failed("action_rate_limited") from err
        except (StayFitConnectionError, StayFitInvalidResponseError) as err:
            raise _failed("write_uncertain") from err

        await _refresh(entry, after_write=True)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register actions independently of the lifecycle of any single account."""

    async def handle_action(call: ServiceCall) -> None:
        await _handle_action(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_FREEZE, handle_action, schema=FREEZE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNFREEZE, handle_action, schema=UNFREEZE_SCHEMA
    )
