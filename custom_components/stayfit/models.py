"""Data models and membership selection for StayFit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class StayFitAccount:
    """An authenticated StayFit account."""

    member_id: str
    username: str
    display_name: str
    token: str


@dataclass(frozen=True, slots=True)
class StayFitFreeze:
    """A membership freeze."""

    date_start: date | None
    date_end: date | None
    days: int

    def is_active(self, today: date) -> bool:
        """Return whether the freeze is active on the supplied date."""
        return (
            self.days > 0
            and self.date_start is not None
            and self.date_end is not None
            and self.date_start <= today < self.date_end
        )


@dataclass(frozen=True, slots=True)
class StayFitMembership:
    """A StayFit membership returned by the cloud API."""

    membership_id: str
    name: str | None
    date_start: date | None
    date_end: date | None
    flag_status: str
    freezes: tuple[StayFitFreeze, ...]

    def covers(self, today: date) -> bool:
        """Return whether today falls inside the membership period."""
        return (
            self.date_start is not None
            and self.date_end is not None
            and self.date_start <= today <= self.date_end
        )

    def is_active(self, today: date) -> bool:
        """Return whether the membership is active."""
        return self.flag_status == "1" and self.covers(today)

    def has_active_freeze(self, today: date) -> bool:
        """Return whether any non-cancelled freeze is active."""
        return any(freeze.is_active(today) for freeze in self.freezes)


@dataclass(frozen=True, slots=True)
class StayFitCoordinatorData:
    """Processed data consumed by StayFit entities."""

    memberships: tuple[StayFitMembership, ...]
    primary: StayFitMembership | None
    subscription_active: bool
    active_subscription_freeze: bool


def parse_date(value: Any) -> date | None:
    """Parse a date-only API value, returning None for malformed values."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _normalise_objects(
    value: Any, *, marker_fields: frozenset[str]
) -> list[dict[str, Any]]:
    """Normalise an API object, keyed object, or list into dictionaries."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    if marker_fields.intersection(value):
        return [value]
    return [item for item in value.values() if isinstance(item, dict)]


def parse_freezes(value: Any) -> tuple[StayFitFreeze, ...]:
    """Parse the API's inconsistent freeze representation."""
    freezes: list[StayFitFreeze] = []
    for item in _normalise_objects(
        value, marker_fields=frozenset({"date_start", "date_end", "days"})
    ):
        try:
            days = int(item.get("days", 0))
        except (TypeError, ValueError):
            days = 0
        freezes.append(
            StayFitFreeze(
                date_start=parse_date(item.get("date_start")),
                date_end=parse_date(item.get("date_end")),
                days=days,
            )
        )
    return tuple(freezes)


def parse_memberships(value: Any) -> tuple[StayFitMembership, ...]:
    """Parse memberships from an API response."""
    memberships: list[StayFitMembership] = []
    for index, item in enumerate(
        _normalise_objects(
            value,
            marker_fields=frozenset(
                {"mmid", "membership_name", "date_start", "date_end"}
            ),
        )
    ):
        membership_id = str(item.get("mmid") or item.get("id") or index)
        raw_name = item.get("membership_name")
        memberships.append(
            StayFitMembership(
                membership_id=membership_id,
                name=str(raw_name) if raw_name not in (None, "") else None,
                date_start=parse_date(item.get("date_start")),
                date_end=parse_date(item.get("date_end")),
                flag_status=str(item.get("flag_status", "")),
                freezes=parse_freezes(item.get("freeze")),
            )
        )
    return tuple(memberships)


def select_primary_membership(
    memberships: tuple[StayFitMembership, ...], today: date
) -> StayFitMembership | None:
    """Select the single membership represented by account entities."""
    if not memberships:
        return None

    active = [membership for membership in memberships if membership.is_active(today)]
    if active:
        return max(active, key=lambda item: item.date_end or date.min)

    suspended = [
        membership
        for membership in memberships
        if membership.flag_status == "3" and membership.covers(today)
    ]
    if suspended:
        return max(suspended, key=lambda item: item.date_end or date.min)

    future = [
        membership
        for membership in memberships
        if membership.date_start is not None and membership.date_start > today
    ]
    if future:
        return min(
            future,
            key=lambda item: (
                item.date_start or date.max,
                -(item.date_end or date.min).toordinal(),
            ),
        )

    expired = [
        membership
        for membership in memberships
        if membership.date_end is not None and membership.date_end < today
    ]
    if expired:
        return max(expired, key=lambda item: item.date_end or date.min)

    return memberships[0]


def build_coordinator_data(
    memberships: tuple[StayFitMembership, ...], today: date
) -> StayFitCoordinatorData:
    """Build entity-ready state from parsed memberships."""
    primary = select_primary_membership(memberships, today)
    return StayFitCoordinatorData(
        memberships=memberships,
        primary=primary,
        subscription_active=primary.is_active(today) if primary else False,
        active_subscription_freeze=(
            primary.has_active_freeze(today) if primary else False
        ),
    )
