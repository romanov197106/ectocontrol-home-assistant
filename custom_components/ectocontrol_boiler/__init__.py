"""EctoControl cabinet telemetry, discovery, and validated commands."""
import asyncio
import json
from datetime import timedelta
import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import logging

DOMAIN = "ectocontrol_boiler"
BASE = "https://my.ectostroy.ru/api/"

class AuthenticationError(Exception):
    """Cabinet authentication rejected."""

class Cabinet:
    def __init__(self, session, email, password):
        self.session, self.email, self.password = session, email, password
        self.token = None

    async def request(self, path, payload):
        # Exact form used by the manufacturer cabinet; restrict command routes.
        from .programs import ROUTES
        if path not in {"user/login", "objects/get_object", "objects/list_objects_with_more_info", "task/send_device_state", *ROUTES.values()}:
            raise ValueError("Unsupported cabinet operation")
        form = aiohttp.FormData()
        form.add_field("j", json.dumps(payload), filename=None,
                       content_type="text/plain")
        async with self.session.post(BASE + path, data=form,
                                     timeout=aiohttp.ClientTimeout(total=20)) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)
        if not isinstance(result, dict):
            raise ValueError("Unexpected cabinet response")
        if result.get("success") is False or result.get("exceptions"):
            raise AuthenticationError("Cabinet rejected request")
        return result

    async def login(self):
        result = await self.request("user/login", {
            "email": self.email, "password": self.password})
        self.token = result.get("token")
        if not self.token:
            raise AuthenticationError("No session token")

    async def read(self, boiler_id, program_id):
        if not self.token:
            await self.login()
        async def get(object_id):
            return await self.request("objects/get_object", {
                "token": self.token, "id_object": object_id})
        try:
            boiler = await get(boiler_id)
            program = await get(program_id)
        except AuthenticationError:
            self.token = None
            await self.login()
            boiler = await get(boiler_id)
            program = await get(program_id)
        if not isinstance(boiler.get("state"), dict) or not isinstance(program.get("config"), dict):
            raise ValueError("Selected objects are unavailable")
        programs = {}
        start = 0
        while True:
            page = await self.request("objects/list_objects_with_more_info", {
                "token": self.token, "local_id_object_group": [10],
                "list_start": start, "list_amount": 100})
            items = page.get("list")
            if not isinstance(items, list):
                raise ValueError("Invalid program list")
            for item in items:
                object_id = int(item["id"])
                programs[object_id] = program if object_id == program_id else await get(object_id)
            start += len(items)
            if len(items) < 100 or start >= int(page.get("item_count", start + 1)):
                break
            if start > 10000:
                raise ValueError("Program list exceeds limit")
        equipment = {}
        start = 0
        while True:
            page = await self.request("objects/list_objects_with_more_info", {
                "token": self.token, "local_id_object_group": [0, 1, 2],
                "list_start": start, "list_amount": 100})
            items = page.get("list")
            if not isinstance(items, list):
                raise ValueError("Invalid equipment list")
            for item in items:
                # Retain telemetry only; never expose account or system passwords.
                safe = {k: item.get(k) for k in ("id", "cloud_type", "info", "state", "lk", "system_connection_status", "connection")}
                safe["config"] = {k: v for k, v in item.get("config", {}).items()
                                  if k in {"name", "unit", "flags", "state_name"}}
                equipment[int(item["id"])] = safe
            start += len(items)
            if len(items) < 100 or start >= int(page.get("item_count", start + 1)):
                break
            if start > 10000:
                raise ValueError("Equipment list exceeds limit")
        return {"boiler": boiler, "program": program, "programs": programs, "equipment": equipment}

class Coordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN,
                         config_entry=entry, update_interval=timedelta(seconds=60))
        self.client = Cabinet(async_get_clientsession(hass),
                              entry.data["email"], entry.data["password"])
        self.ids = entry.data["boiler_id"], entry.data["program_id"]
        self.command_lock = asyncio.Lock()

    async def _async_update_data(self):
        try:
            return await self.client.read(*self.ids)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Check cabinet login and object access") from err
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise UpdateFailed("Cannot read cabinet data") from err

    async def set_program(self, object_id, field, value):
        from .programs import validate_command, ROUTES
        from homeassistant.exceptions import HomeAssistantError
        program = self.data.get("programs", {}).get(object_id)
        if program is None:
            raise HomeAssistantError("Программа отсутствует в кабинете")
        validate_command(program, field, value)
        try:
            # Never retry a command: a timeout may occur after it was accepted.
            await self.client.request(ROUTES[int(program["cloud_type"])], {
                "token": self.client.token, "id_object": object_id, field: value})
        except (AuthenticationError, aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise HomeAssistantError("Не удалось подтвердить команду. Проверьте состояние в кабинете.") from err
        await self.async_request_refresh()

    async def set_equipment(self, object_id, value):
        from .equipment import validate_switch
        from homeassistant.exceptions import HomeAssistantError
        async with self.command_lock:
            await self.async_request_refresh()
            device = self.data.get("equipment", {}).get(object_id)
            validate_switch(device, value)
            try:
                await self.client.request("task/send_device_state", {
                    "token": self.client.token, "id_object": object_id, "state": value})
            except (AuthenticationError, aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                raise HomeAssistantError("Не удалось подтвердить команду оборудования. Проверьте кабинет.") from err
            await self.async_request_refresh()

    async def set_boiler(self, field, value):
        async with self.command_lock:
            await self._set_boiler_locked(field, value)

    async def _set_boiler_locked(self, field, value):
        from .programs import validate_command, ROUTES, LIMIT_PAIRS
        from homeassistant.exceptions import HomeAssistantError
        boiler = dict(self.data["boiler"], cloud_type=-1)
        validate_command(boiler, field, value)
        changes = {field: value}
        for low, high in LIMIT_PAIRS:
            if field in (low, high):
                other = high if field == low else low
                changes[other] = boiler["config"][other]
        try:
            await self.client.request(ROUTES[-1], {
                "token": self.client.token, "id_object": self.ids[0], **changes})
        except (AuthenticationError, aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise HomeAssistantError("Не удалось подтвердить команду котла. Проверьте кабинет.") from err
        await self.async_request_refresh()

async def async_setup_entry(hass, entry):
    coordinator = Coordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "number", "select", "switch"])
    return True

async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, ["sensor", "number", "select", "switch"]):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False
