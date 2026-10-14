"""Asynchronous client for the StayFit cloud API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
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
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if authenticated:
            if not self._token:
                raise StayFitAuthenticationError
            headers["Auth"] = f"Bearer {self._token}"

        try:
            async with asyncio.timeout(15):
                response = await self._session.post(
                    f"{API_BASE_URL}/{endpoint}?json",
                    params=params,
                    data=data,
                    headers=headers,
                )
                if response.status == HTTP_TOO_MANY_REQUESTS:
                    raise StayFitRateLimitError
                response.raise_for_status()
                try:
                    payload = await response.json(content_type=None)
                except (json.JSONDecodeError, ValueError, TypeError) as err:
                    raise StayFitInvalidResponseError from err
        except StayFitError:
            raise
        except (TimeoutError, ClientError) as err:
            raise StayFitConnectionError from err

        if not isinstance(payload, dict):
            raise StayFitInvalidResponseError
        return payload

    @staticmethod
    def _error_code(payload: Mapping[str, Any]) -> str | None:
        error = payload.get("error")
        if error in (None, "", {}, []):
            return None
        if isinstance(error, list):
            return ",".join(str(item) for item in error)
        return str(error)

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
        if error == "ERROR_LOGIN_MEMBER":
            raise StayFitAuthenticationError
        if error in {"MSG_NO_MEMBERSHIPS_FOUND", "NO_MEMBERSHIPS"}:
            return ()
        if error:
            raise StayFitApiError(error)
        return parse_memberships(payload.get("membership"))
