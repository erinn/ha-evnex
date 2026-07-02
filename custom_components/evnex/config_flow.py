"""Config flow for Evnex EV Charger integration."""

from __future__ import annotations

import logging
from typing import Any, Literal

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.httpx_client import get_async_client
from pycognito.exceptions import (
    SMSMFAChallengeException,
    SoftwareTokenMFAChallengeException,
)

from evnex.api import Evnex
from evnex.errors import NotAuthorizedException

from .const import DOMAIN

logger = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

MFA_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("code"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    httpx_client = get_async_client(hass)
    evnex_client = await hass.async_add_executor_job(
        Evnex,
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        None,
        None,
        None,
        None,
        httpx_client,
    )
    try:
        await hass.async_add_executor_job(evnex_client.authenticate)
    except SMSMFAChallengeException:
        raise MfaRequired("SMS", evnex_client)
    except SoftwareTokenMFAChallengeException:
        raise MfaRequired("TOTP", evnex_client)
    except NotAuthorizedException:
        raise InvalidAuth

    user_data = await evnex_client.get_user_detail()
    logger.info("Have initial user data from evnex cloud API")

    unique_id = user_data.id

    # Return info that you want to store in the config entry.
    return {
        CONF_USERNAME: data[CONF_USERNAME],
        CONF_PASSWORD: data[CONF_PASSWORD],
        "unique_id": unique_id,
        "title": user_data.name,
        "user_id": user_data.id,
        "default_org_id": evnex_client.org_id,
        "id_token": evnex_client.id_token,
        "refresh_token": evnex_client.refresh_token,
        "access_token": evnex_client.access_token,
    }


class EvnexConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore
    """Handle a config flow for Evnex EV Charger."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] | None = None
        self._mfa_mode: Literal["SMS", "TOTP"] | None = None
        self._evnex_client: Evnex | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle reauth."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth confirmation."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
                description_placeholders={CONF_USERNAME: self._reauth_entry.data[CONF_USERNAME]},
            )

        errors = {}
        user_input[CONF_USERNAME] = self._reauth_entry.data[CONF_USERNAME]

        try:
            info = await validate_input(self.hass, user_input)
        except MfaRequired as err:
            self._user_input = user_input
            self._mfa_mode = err.mode
            self._evnex_client = err.client
            return await self.async_step_mfa()
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_credentials"
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data={
                    **self._reauth_entry.data,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    "id_token": info["id_token"],
                    "refresh_token": info["refresh_token"],
                    "access_token": info["access_token"],
                },
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: self._reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except MfaRequired as err:
            self._user_input = user_input
            self._mfa_mode = err.mode
            self._evnex_client = err.client
            return await self.async_step_mfa()
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_credentials"
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=info["title"],
                data={
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    "user_id": info["user_id"],
                    "default_org_id": info["default_org_id"],
                    "id_token": info["id_token"],
                    "refresh_token": info["refresh_token"],
                    "access_token": info["access_token"],
                },
            )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle MFA step."""
        if user_input is None:
            return self.async_show_form(step_id="mfa", data_schema=MFA_DATA_SCHEMA)

        errors = {}
        mfa_code = user_input["code"]

        try:
            await self.hass.async_add_executor_job(
                self._evnex_client.respond_to_mfa_challenge, mfa_code, self._mfa_mode
            )

            user_data = await self._evnex_client.get_user_detail()

            if self._reauth_entry:
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_PASSWORD: self._user_input[CONF_PASSWORD],
                        "id_token": self._evnex_client.id_token,
                        "refresh_token": self._evnex_client.refresh_token,
                        "access_token": self._evnex_client.access_token,
                    },
                )

            return self.async_create_entry(
                title=user_data.name,
                data={
                    CONF_USERNAME: self._user_input[CONF_USERNAME],
                    CONF_PASSWORD: self._user_input[CONF_PASSWORD],
                    "user_id": user_data.id,
                    "default_org_id": self._evnex_client.org_id,
                    "id_token": self._evnex_client.id_token,
                    "refresh_token": self._evnex_client.refresh_token,
                    "access_token": self._evnex_client.access_token,
                },
            )

        except NotAuthorizedException:
            errors["base"] = "invalid_mfa_code"
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected exception during MFA")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="mfa", data_schema=MFA_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class MfaRequired(HomeAssistantError):
    """Error to indicate MFA is required."""

    def __init__(self, mode: Literal["SMS", "TOTP"], client: Evnex) -> None:
        """Initialize."""
        super().__init__()
        self.mode = mode
        self.client = client
