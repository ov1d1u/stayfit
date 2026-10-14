"""Tests for the StayFit config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stayfit.api import (
    StayFitAuthenticationError,
    StayFitConnectionError,
    StayFitRateLimitError,
)
from custom_components.stayfit.const import (
    CONF_DISPLAY_NAME,
    CONF_MEMBER_ID,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.stayfit.models import StayFitAccount

USER_INPUT = {CONF_USERNAME: "User@Example.com", CONF_PASSWORD: "1234"}
ACCOUNT = StayFitAccount(
    member_id="123",
    username="user@example.com",
    display_name="Test Member",
    token="secret-token",
)


@pytest.fixture(autouse=True)
def prevent_entry_setup():
    """Keep config-flow tests isolated from coordinator setup."""
    with patch(
        "custom_components.stayfit.async_setup_entry", AsyncMock(return_value=True)
    ):
        yield


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A valid account creates a credential-safe config entry."""
    with patch(
        "custom_components.stayfit.config_flow._async_validate_input",
        AsyncMock(return_value=ACCOUNT),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Member"
    assert result["result"].unique_id == "123"
    assert result["data"] == {
        CONF_USERNAME: "user@example.com",
        CONF_TOKEN: "secret-token",
        CONF_MEMBER_ID: "123",
        CONF_DISPLAY_NAME: "Test Member",
    }
    assert CONF_PASSWORD not in result["data"]


async def test_duplicate_account_is_rejected(hass: HomeAssistant) -> None:
    """The same member ID cannot be configured twice."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="123",
        data={CONF_MEMBER_ID: "123"},
    ).add_to_hass(hass)

    with patch(
        "custom_components.stayfit.config_flow._async_validate_input",
        AsyncMock(return_value=ACCOUNT),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_distinct_accounts_are_allowed(hass: HomeAssistant) -> None:
    """Different StayFit member IDs can coexist."""
    for member_id in ("123", "456"):
        account = StayFitAccount(
            member_id=member_id,
            username=f"{member_id}@example.com",
            display_name=f"Member {member_id}",
            token=f"token-{member_id}",
        )
        with patch(
            "custom_components.stayfit.config_flow._async_validate_input",
            AsyncMock(return_value=account),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data=USER_INPUT,
            )
        assert result["type"] is FlowResultType.CREATE_ENTRY

    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


async def test_user_flow_errors(hass: HomeAssistant) -> None:
    """Known failures map to actionable form errors."""
    cases = (
        (StayFitAuthenticationError(), "invalid_auth"),
        (StayFitRateLimitError(), "rate_limited"),
        (StayFitConnectionError(), "cannot_connect"),
    )
    for exception, expected_error in cases:
        with patch(
            "custom_components.stayfit.config_flow._async_validate_input",
            AsyncMock(side_effect=exception),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data=USER_INPUT,
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": expected_error}


async def test_reauth_updates_token(hass: HomeAssistant) -> None:
    """Reauthentication replaces credentials without creating a new entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Member",
        unique_id="123",
        data={
            CONF_USERNAME: "old@example.com",
            CONF_TOKEN: "old-token",
            CONF_MEMBER_ID: "123",
            CONF_DISPLAY_NAME: "Test Member",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.stayfit.config_flow._async_validate_input",
            AsyncMock(return_value=ACCOUNT),
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "secret-token"
    assert CONF_PASSWORD not in entry.data


async def test_reauth_rejects_different_account(hass: HomeAssistant) -> None:
    """Credentials for another member cannot replace an existing account."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Member",
        unique_id="123",
        data={CONF_MEMBER_ID: "123"},
    )
    entry.add_to_hass(hass)
    other_account = StayFitAccount(
        member_id="999",
        username="other@example.com",
        display_name="Other Member",
        token="other-token",
    )

    with patch(
        "custom_components.stayfit.config_flow._async_validate_input",
        AsyncMock(return_value=other_account),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_account"}
