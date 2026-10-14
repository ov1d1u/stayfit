"""Tests for the StayFit API client."""

import re

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.stayfit.api import (
    StayFitApiClient,
    StayFitAuthenticationError,
    StayFitConnectionError,
    StayFitInvalidResponseError,
    StayFitRateLimitError,
)
from custom_components.stayfit.const import API_PROJECT


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
