"""Tests for StayFit membership parsing and selection."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from custom_components.stayfit.models import (
    build_coordinator_data,
    parse_checkins,
    parse_dashboard,
    parse_memberships,
    select_primary_membership,
)

TODAY = date(2026, 10, 9)


def _membership(
    membership_id: str,
    start: str,
    end: str,
    *,
    status: str = "1",
    name: str | None = None,
    freeze=None,
):
    return {
        "mmid": membership_id,
        "membership_name": name or f"Plan {membership_id}",
        "date_start": start,
        "date_end": end,
        "flag_status": status,
        "freeze": freeze,
    }


def test_selects_active_membership_with_latest_expiry() -> None:
    """The longest-running active membership is primary."""
    memberships = parse_memberships(
        [
            _membership("1", "2026-01-01", "2026-10-10"),
            _membership("2", "2026-02-01", "2027-02-01"),
        ]
    )

    assert select_primary_membership(memberships, TODAY).membership_id == "2"


def test_selection_fallback_order() -> None:
    """Suspended, future, and expired memberships follow the defined order."""
    suspended = parse_memberships(
        [_membership("s", "2026-01-01", "2026-12-01", status="3")]
    )
    assert select_primary_membership(suspended, TODAY).membership_id == "s"

    future = parse_memberships(
        [
            _membership("later", "2027-02-01", "2028-01-01"),
            _membership("next", "2026-11-01", "2027-01-01"),
        ]
    )
    assert select_primary_membership(future, TODAY).membership_id == "next"

    expired = parse_memberships(
        [
            _membership("old", "2024-01-01", "2024-12-31"),
            _membership("recent", "2025-01-01", "2026-09-01"),
        ]
    )
    assert select_primary_membership(expired, TODAY).membership_id == "recent"


def test_membership_end_date_is_inclusive() -> None:
    """A subscription stays active for its full final calendar day."""
    memberships = parse_memberships([_membership("1", "2026-01-01", "2026-10-09")])

    assert build_coordinator_data(memberships, TODAY).subscription_active is True


def test_freeze_end_date_is_exclusive_and_cancelled_freezes_are_ignored() -> None:
    """Freeze behavior matches the Android app."""
    active = _membership(
        "1",
        "2026-01-01",
        "2026-12-31",
        freeze={"date_start": "2026-10-01", "date_end": "2026-10-10", "days": "9"},
    )
    data = build_coordinator_data(parse_memberships([active]), TODAY)
    assert data.active_subscription_freeze is True

    at_end = build_coordinator_data(parse_memberships([active]), date(2026, 10, 10))
    assert at_end.active_subscription_freeze is False

    active["freeze"] = [
        {"date_start": "2026-10-01", "date_end": "2026-10-20", "days": "0"}
    ]
    cancelled = build_coordinator_data(parse_memberships([active]), TODAY)
    assert cancelled.active_subscription_freeze is False


def test_keyed_objects_and_invalid_dates_are_safe() -> None:
    """Keyed API objects and malformed dates do not crash state processing."""
    memberships = parse_memberships(
        {
            "42": _membership("42", "not-a-date", "also-invalid"),
        }
    )
    data = build_coordinator_data(memberships, TODAY)

    assert data.primary is not None
    assert data.primary.membership_id == "42"
    assert data.primary.date_end is None
    assert data.subscription_active is False


def test_no_memberships_produces_empty_states() -> None:
    """An account without memberships is a valid state."""
    data = build_coordinator_data((), TODAY)

    assert data.primary is None
    assert data.subscription_active is False
    assert data.active_subscription_freeze is False


def test_parses_additional_membership_sensor_fields() -> None:
    """Payment, penalties, and voucher counters retain valid API values."""
    membership = parse_memberships(
        [
            {
                **_membership("1", "2026-01-01", "2026-12-31"),
                "recurrent": "1",
                "next_payment_date": "2026-11-15 00:00:00",
                "total_penalties": "2",
                "penalty_limit": 5,
                "slots_available": "3",
            }
        ]
    )[0]

    assert membership.recurrent is True
    assert membership.next_payment_date == date(2026, 11, 15)
    assert membership.total_penalties == 2
    assert membership.penalty_limit == 5
    assert membership.slots_available == 3


def test_parses_dashboard_counters_and_checkins() -> None:
    """Official dashboard and history response shapes become typed data."""
    dashboard = parse_dashboard(
        {
            "member_activity_stats": {"checkins_30": "8"},
            "unread_emails": 3,
        }
    )
    checkins = parse_checkins(
        {
            "older": {
                "date_checkin": "2026-10-08 10:00:00",
                "club_name": "Stay Fit Central",
            },
            "newer": {
                "date_checkin": "2026-10-09 18:30:00",
                "club_name": "Stay Fit Unirii",
            },
        }
    )

    assert dashboard.checkins_last_30_days == 8
    assert dashboard.unread_messages == 3
    assert checkins[0].club == "Stay Fit Unirii"
    assert checkins[0].checked_in_at == datetime(
        2026, 10, 9, 18, 30, tzinfo=ZoneInfo("Europe/Bucharest")
    )


def test_malformed_optional_sensor_data_is_unknown() -> None:
    """Optional counters never guess at malformed API values."""
    membership = parse_memberships(
        [
            {
                **_membership("1", "2026-01-01", "2026-12-31"),
                "next_payment_date": "invalid",
                "total_penalties": True,
                "penalty_limit": "invalid",
                "slots_available": None,
            }
        ]
    )[0]
    dashboard = parse_dashboard(
        {"member_activity_stats": {"checkins_30": -1}, "unread_emails": "bad"}
    )

    assert membership.next_payment_date is None
    assert membership.total_penalties is None
    assert membership.penalty_limit is None
    assert membership.slots_available is None
    assert dashboard.checkins_last_30_days == -1
    assert dashboard.unread_messages is None
