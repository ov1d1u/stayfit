"""Config flow for StayFit."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    StayFitApiClient,
    StayFitApiError,
    StayFitAuthenticationError,
    StayFitConnectionError,
    StayFitInvalidResponseError,
    StayFitRateLimitError,
)
from .const import CONF_DISPLAY_NAME, CONF_MEMBER_ID, CONF_TOKEN, DOMAIN
from .models import StayFitAccount

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


async def _async_validate_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> StayFitAccount:
    """Authenticate user input and return account metadata."""
    client = StayFitApiClient(async_get_clientsession(hass))
    return await client.async_login(
        user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
    )


def _entry_data(account: StayFitAccount) -> dict[str, str]:
    """Return credential-safe config entry data."""
    return {
        CONF_USERNAME: account.username,
        CONF_TOKEN: account.token,
        CONF_MEMBER_ID: account.member_id,
        CONF_DISPLAY_NAME: account.display_name,
    }


class StayFitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a StayFit config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                account = await _async_validate_input(self.hass, user_input)
            except StayFitAuthenticationError:
                errors["base"] = "invalid_auth"
            except StayFitRateLimitError:
                errors["base"] = "rate_limited"
            except StayFitConnectionError:
                errors["base"] = "cannot_connect"
            except (StayFitApiError, StayFitInvalidResponseError):
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected exception validating StayFit account")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(account.member_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=account.display_name,
                    data=_entry_data(account),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Begin reauthentication for an existing account."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate replacement credentials and update the token."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                account = await _async_validate_input(self.hass, user_input)
            except StayFitAuthenticationError:
                errors["base"] = "invalid_auth"
            except StayFitRateLimitError:
                errors["base"] = "rate_limited"
            except StayFitConnectionError:
                errors["base"] = "cannot_connect"
            except (StayFitApiError, StayFitInvalidResponseError):
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception(
                    "Unexpected exception reauthenticating StayFit account"
                )
                errors["base"] = "unknown"
            else:
                expected_member_id = str(reauth_entry.data[CONF_MEMBER_ID])
                if account.member_id != expected_member_id:
                    errors["base"] = "wrong_account"
                else:
                    await self.async_set_unique_id(account.member_id)
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data_updates=_entry_data(account),
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"account": reauth_entry.title},
        )
