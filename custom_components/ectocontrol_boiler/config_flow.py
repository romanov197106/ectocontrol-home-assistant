"""User-entered cabinet credentials; validate read access before saving."""
import asyncio
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from . import DOMAIN, Cabinet, AuthenticationError

class Flow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input['email'].strip().lower()}_{user_input['boiler_id']}_{user_input['program_id']}")
            self._abort_if_unique_id_configured()
            client = Cabinet(async_get_clientsession(self.hass),
                             user_input["email"].strip(), user_input["password"])
            try:
                await client.read(user_input["boiler_id"], user_input["program_id"])
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, asyncio.TimeoutError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_objects"
            else:
                user_input["email"] = user_input["email"].strip()
                return self.async_create_entry(title="Эктоконтроль программы", data=user_input)
        schema = vol.Schema({
            vol.Required("email"): str,
            vol.Required("password"): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Required("boiler_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required("program_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            data = dict(self._reauth_entry.data)
            data.update(user_input)
            try:
                await Cabinet(async_get_clientsession(self.hass), data["email"], data["password"]).read(data["boiler_id"], data["program_id"])
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(self._reauth_entry, data_updates=data)
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({
            vol.Required("password"): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))}), errors=errors)
