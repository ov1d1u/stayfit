"""Asynchronous client for the StayFit cloud API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import date
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import API_BASE_URL, API_LANGUAGE_ID, API_PROJECT
from .models import StayFitAccount, StayFitMembership, parse_memberships

HTTP_TOO_MANY_REQUESTS = 429


class StayFitError(Exception):
    """Base StayFit exception."""


class StayFitConnectionError(StayFitError):
    """The StayFit API could not be reached."""


class StayFitAuthenticationError(StayFitError):
    """The supplied credentials or token are invalid."""


class StayFitTimeoutError(StayFitConnectionError):
    """A request timed out; a write may already have been applied."""


class StayFitRateLimitError(StayFitError):
    """The StayFit API rejected requests temporarily."""


class StayFitInvalidResponseError(StayFitError):
    """The StayFit API returned an unexpected response."""


class StayFitApiError(StayFitError):
    """The StayFit API returned an application error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class StayFitApiClient:
    """Small client implementing the API calls required by Home Assistant."""

    def __init__(self, session: ClientSession, token: str | None = None) -> None:
        self._session = session
        self._token = token

    @property
    def token(self) -> str | None:
        """Return the current bearer token."""
        return self._token

    async def _post(
        self,
        endpoint: str,
        *,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str],
        authenticated: bool = False,
        json_query: bool = True,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if authenticated:
            if not self._token:
                raise StayFitAuthenticationError
            headers["Auth"] = f"Bearer {self._token}"

        try:
            async with asyncio.timeout(15):
                async with self._session.post(
                    f"{API_BASE_URL}/{endpoint}" + ("?json" if json_query else ""),
                    params=params,
                    data=data,
                    headers=headers,
                ) as response:
                    if response.status == HTTP_TOO_MANY_REQUESTS:
                        raise StayFitRateLimitError
                    if response.status in (401, 403):
                        raise StayFitAuthenticationError
                    response.raise_for_status()
                    try:
                        payload = await response.json(content_type=None)
                    except (json.JSONDecodeError, ValueError, TypeError) as err:
                        raise StayFitInvalidResponseError from err
        except StayFitError:
            raise
        except TimeoutError as err:
            raise StayFitTimeoutError from err
        except ClientError as err:
            raise StayFitConnectionError from err

        if not isinstance(payload, dict):
            raise StayFitInvalidResponseError
        return payload

    @staticmethod
    def _error_code(payload: Mapping[str, Any]) -> str | None:
        error = payload.get("error")
        if error in (None, "", {}, [], False):
            return None
        if isinstance(error, dict):
            return (
                ",".join(
                    value
                    for item in error.values()
                    if (value := StayFitApiClient._error_code({"error": item}))
                )
                or None
            )
        if isinstance(error, list):
            return (
                ",".join(
                    value
                    for item in error
                    if (value := StayFitApiClient._error_code({"error": item}))
                )
                or None
            )
        return str(error)

    def _raise_response_error(self, payload: Mapping[str, Any]) -> None:
        """Classify authenticated API errors, including structured errors."""
        if error := self._error_code(payload):
            codes = error.split(",")
            if "ERROR_LOGIN_MEMBER" in codes:
                raise StayFitAuthenticationError
            if "ERROR_LOGIN_TOO_MANY_ATTEMPTS" in codes:
                raise StayFitRateLimitError
            raise StayFitApiError(error)

    async def async_login(self, username: str, password: str) -> StayFitAccount:
        """Authenticate and return stable member metadata."""
        normalized_username = username.strip().lower()
        payload = await self._post(
            "authenticate.php",
            params={"email": normalized_username, "pincode": password},
            data={"project": API_PROJECT},
        )
        error = self._error_code(payload)
        if error in {"ERROR_LOGIN_MEMBER", "WRONG_REQUEST_PARAMETERS"}:
            raise StayFitAuthenticationError
        if error == "ERROR_LOGIN_TOO_MANY_ATTEMPTS":
            raise StayFitRateLimitError
        if error:
            raise StayFitApiError(error)

        token = payload.get("token")
        member = payload.get("member")
        if not isinstance(token, str) or not token or not isinstance(member, dict):
            raise StayFitInvalidResponseError
        member_id = member.get("id")
        if member_id in (None, ""):
            raise StayFitInvalidResponseError

        first_name = str(member.get("fname") or "").strip()
        last_name = str(member.get("lname") or "").strip()
        display_name = " ".join(part for part in (first_name, last_name) if part)
        if not display_name:
            display_name = str(member.get("email") or normalized_username)

        self._token = token
        return StayFitAccount(
            member_id=str(member_id),
            username=normalized_username,
            display_name=display_name,
            token=token,
        )

    async def async_get_memberships(self) -> tuple[StayFitMembership, ...]:
        """Fetch and parse all memberships for the authenticated account."""
        payload = await self._post(
            "member-memberships.php",
            data={"project": API_PROJECT, "lang": API_LANGUAGE_ID},
            authenticated=True,
        )
        error = self._error_code(payload)
        if error in {"MSG_NO_MEMBERSHIPS_FOUND", "NO_MEMBERSHIPS"}:
            return ()
        self._raise_response_error(payload)
        if "membership" not in payload:
            raise StayFitInvalidResponseError
        return parse_memberships(payload.get("membership"))

    async def async_freeze_subscription(
        self, subscription_id: str, start_date: date, days: int
    ) -> None:
        """Create a personal freeze using the Android app's request contract."""
        payload = await self._post(
            "freeze-membership.php",
            data={
                "project": API_PROJECT,
                "lang": API_LANGUAGE_ID,
                "mmid": subscription_id,
                "reason": "2",
                "date_start": start_date.isoformat(),
                "days": str(days),
            },
            authenticated=True,
        )
        self._raise_response_error(payload)
        if "freeze" not in payload or payload["freeze"] is None:
            raise StayFitInvalidResponseError

    async def async_unfreeze_subscription(self, freeze_id: str) -> None:
        """Stop one freeze using the Android app's request contract."""
        payload = await self._post(
            "stop-freeze.php",
            data={"project": API_PROJECT, "mmfid": freeze_id},
            authenticated=True,
            json_query=False,
        )
        self._raise_response_error(payload)
        if "success" not in payload or payload["success"] is None:
            raise StayFitInvalidResponseError
