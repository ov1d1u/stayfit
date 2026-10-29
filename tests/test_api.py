"""Tests for the StayFit API client."""

import re
from datetime import date

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.stayfit.api import (
    StayFitApiClient,
    StayFitApiError,
    StayFitAuthenticationError,
    StayFitConnectionError,
    StayFitInvalidResponseError,
    StayFitRateLimitError,
    StayFitTimeoutError,
)
from custom_components.stayfit.const import API_APP_VERSION, API_PROJECT


@pytest.mark.asyncio
async def test_login_request_and_response() -> None:
    """Login uses the API's exact query/body contract and parses identity."""
    pattern = re.compile(r"https://api\.upfit\.cloud/authenticate\.php.*")
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(
                pattern,
                payload={
                    "token": "secret-token",
                    "member": {
                        "id": 123,
                        "fname": "Ada",
                        "lname": "Lovelace",
                        "email": "ada@example.com",
                    },
                },
            )
            account = await StayFitApiClient(session).async_login(
                " Ada@Example.COM ", "1234"
            )

    assert account.member_id == "123"
    assert account.username == "ada@example.com"
    assert account.display_name == "Ada Lovelace"
    assert account.token == "secret-token"
    request = next(iter(mocked.requests.values()))[0]
    request_url = next(iter(mocked.requests))[1]
    assert request_url.query["email"] == "ada@example.com"
    assert request_url.query["pincode"] == "1234"
    assert request.kwargs["data"] == {"project": API_PROJECT}
    assert request.kwargs["headers"]["Content-Type"].startswith(
        "application/x-www-form-urlencoded"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "exception"),
    [
        ({"error": "ERROR_LOGIN_MEMBER"}, StayFitAuthenticationError),
        ({"error": "WRONG_REQUEST_PARAMETERS"}, StayFitAuthenticationError),
        ({"error": "ERROR_LOGIN_TOO_MANY_ATTEMPTS"}, StayFitRateLimitError),
        ({"member": {"id": "1"}}, StayFitInvalidResponseError),
    ],
)
async def test_login_errors(payload, exception) -> None:
    """Login errors are classified for the config flow."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(re.compile(r"https://api\.upfit\.cloud/.*"), payload=payload)
            with pytest.raises(exception):
                await StayFitApiClient(session).async_login("user@example.com", "1234")


@pytest.mark.asyncio
async def test_membership_request_uses_auth_header() -> None:
    """Membership polling sends the app's nonstandard Auth header."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(
                re.compile(r"https://api\.upfit\.cloud/member-memberships\.php.*"),
                payload={
                    "membership": [
                        {
                            "mmid": "9",
                            "membership_name": "Gold",
                            "date_start": "2026-01-01",
                            "date_end": "2026-12-31",
                            "flag_status": "1",
                        }
                    ]
                },
            )
            memberships = await StayFitApiClient(
                session, token="secret-token"
            ).async_get_memberships()

    assert memberships[0].name == "Gold"
    request = next(iter(mocked.requests.values()))[0]
    assert request.kwargs["headers"]["Auth"] == "Bearer secret-token"
    assert request.kwargs["data"] == {"project": API_PROJECT, "lang": "2"}


@pytest.mark.asyncio
async def test_no_memberships_is_not_an_error() -> None:
    """The API's empty-membership error is a valid empty response."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(
                re.compile(r"https://api\.upfit\.cloud/.*"),
                payload={"error": "MSG_NO_MEMBERSHIPS_FOUND"},
            )
            assert (
                await StayFitApiClient(
                    session, token="secret-token"
                ).async_get_memberships()
                == ()
            )


@pytest.mark.asyncio
async def test_dashboard_request_and_response() -> None:
    """Dashboard polling matches the official app and parses requested counters."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(
                re.compile(
                    r"https://api\.upfit\.cloud/member-get-dashboard-info\.php.*"
                ),
                payload={
                    "member_activity_stats": {"checkins_30": "7"},
                    "unread_emails": "4",
                },
            )
            dashboard = await StayFitApiClient(
                session, token="secret-token"
            ).async_get_dashboard("123")

    assert dashboard.checkins_last_30_days == 7
    assert dashboard.unread_messages == 4
    request = next(iter(mocked.requests.values()))[0]
    assert request.kwargs["headers"]["Auth"] == "Bearer secret-token"
    assert request.kwargs["data"] == {
        "project": API_PROJECT,
        "mbid": "123",
        "lang": "2",
        "device_type": "0",
        "app_version": "3",
        "app_version_store": API_APP_VERSION,
    }


@pytest.mark.asyncio
async def test_latest_checkin_request_and_response() -> None:
    """The latest check-in retains both its timestamp and club."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(
                re.compile(r"https://api\.upfit\.cloud/member-get-checkins\.php.*"),
                payload={
                    "checkins": {
                        "1": {
                            "date_checkin": "2026-10-09 18:30:00",
                            "club_name": "Stay Fit Unirii",
                        }
                    }
                },
            )
            checkin = await StayFitApiClient(
                session, token="secret-token"
            ).async_get_latest_checkin()

    assert checkin is not None
    assert checkin.club == "Stay Fit Unirii"
    assert checkin.checked_in_at is not None
    assert checkin.checked_in_at.isoformat() == "2026-10-09T18:30:00+03:00"
    request = next(iter(mocked.requests.values()))[0]
    assert request.kwargs["headers"]["Auth"] == "Bearer secret-token"
    assert request.kwargs["data"] == {
        "project": API_PROJECT,
        "page": "1",
        "articles_per_page": "1",
    }


@pytest.mark.asyncio
async def test_no_checkins_is_not_an_error() -> None:
    """An account without check-ins has an unknown latest visit."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(
                re.compile(r"https://api\.upfit\.cloud/member-get-checkins\.php.*"),
                payload={"error": "MSG_NO_CHECKINS_FOUND"},
            )
            assert (
                await StayFitApiClient(
                    session, token="secret-token"
                ).async_get_latest_checkin()
                is None
            )


@pytest.mark.asyncio
async def test_http_rate_limit_is_classified() -> None:
    """An HTTP 429 response is exposed as a rate-limit error."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(re.compile(r"https://api\.upfit\.cloud/.*"), status=429)
            with pytest.raises(StayFitRateLimitError):
                await StayFitApiClient(session).async_login("user@example.com", "1234")


@pytest.mark.asyncio
async def test_network_failure_is_classified() -> None:
    """Transport failures are exposed as connection errors."""
    with aioresponses() as mocked:
        async with ClientSession() as session:
            mocked.post(
                re.compile(r"https://api\.upfit\.cloud/.*"),
                exception=TimeoutError,
            )
            with pytest.raises(StayFitConnectionError):
                await StayFitApiClient(session).async_login("user@example.com", "1234")


@pytest.mark.parametrize("operation", ["freeze", "unfreeze"])
async def test_write_request_contract(operation) -> None:
    """Both mutations exactly match app URLs, headers and form bodies."""
    url = (
        "https://api.upfit.cloud/freeze-membership.php?json"
        if operation == "freeze"
        else "https://api.upfit.cloud/stop-freeze.php"
    )
    payload = (
        {"freeze": {"date_end_new": "2027-01-07"}}
        if operation == "freeze"
        else {"success": 1}
    )
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.post(url, payload=payload)
            client = StayFitApiClient(session, token="mock-token")
            if operation == "freeze":
                await client.async_freeze_subscription("123", date(2026, 11, 1), 7)
            else:
                await client.async_unfreeze_subscription("456")

            assert len(mocked.requests) == 1
            (method, actual_url), [request] = next(iter(mocked.requests.items()))
            assert method == "POST"
            assert actual_url.path == url.split("upfit.cloud")[1].split("?")[0]
            assert ("json" in actual_url.query) is (operation == "freeze")
            assert request.kwargs["headers"] == {
                "Auth": "Bearer mock-token",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            expected = {"project": API_PROJECT, "mmfid": "456"}
            if operation == "freeze":
                expected = {
                    "project": API_PROJECT,
                    "lang": "2",
                    "mmid": "123",
                    "reason": "2",
                    "date_start": "2026-11-01",
                    "days": "7",
                }
            assert request.kwargs["data"] == expected


@pytest.mark.parametrize("operation", ["freeze", "unfreeze"])
@pytest.mark.parametrize(
    ("payload", "exception"),
    [
        ({"error": "ERROR_LOGIN_MEMBER"}, StayFitAuthenticationError),
        ({"error": {"auth": ["ERROR_LOGIN_MEMBER"]}}, StayFitAuthenticationError),
        ({"error": ["ERROR_LOGIN_TOO_MANY_ATTEMPTS"]}, StayFitRateLimitError),
        ({"error": {"period": "ERROR_FREEZE_PERIOD_OVERLAPS"}}, StayFitApiError),
        ({"error": ["REJECTED", "INVALID"]}, StayFitApiError),
        ({}, StayFitInvalidResponseError),
        ({"freeze": None, "success": None}, StayFitInvalidResponseError),
        ([], StayFitInvalidResponseError),
    ],
)
async def test_write_response_errors(operation, payload, exception) -> None:
    """Malformed and structured error responses cannot be treated as success."""
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.post(re.compile(r"https://api\.upfit\.cloud/.*"), payload=payload)
            client = StayFitApiClient(session, token="mock-token")
            request = (
                client.async_freeze_subscription("123", date(2026, 11, 1), 7)
                if operation == "freeze"
                else client.async_unfreeze_subscription("456")
            )
            with pytest.raises(exception):
                await request
            assert sum(len(calls) for calls in mocked.requests.values()) == 1


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (401, StayFitAuthenticationError),
        (403, StayFitAuthenticationError),
        (429, StayFitRateLimitError),
        (500, StayFitConnectionError),
    ],
)
async def test_write_http_errors(status, exception) -> None:
    """Classify HTTP failures without retrying the subscription write."""
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.post("https://api.upfit.cloud/stop-freeze.php", status=status)
            with pytest.raises(exception):
                await StayFitApiClient(
                    session, token="mock-token"
                ).async_unfreeze_subscription("456")
            assert sum(len(calls) for calls in mocked.requests.values()) == 1


async def test_write_timeout_is_not_retried() -> None:
    """A timeout retains its type so callers can report an uncertain outcome."""
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.post(
                "https://api.upfit.cloud/stop-freeze.php", exception=TimeoutError()
            )
            with pytest.raises(StayFitTimeoutError):
                await StayFitApiClient(
                    session, token="mock-token"
                ).async_unfreeze_subscription("456")
            assert sum(len(calls) for calls in mocked.requests.values()) == 1
