from . import DOMAIN
from .programs import discover

async def async_setup_entry(hass, entry, async_add_entities):
    discover(hass.data[DOMAIN][entry.entry_id], entry, async_add_entities, 'select')
