"""Automatic discovery of cloud equipment without overriding program locks."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import DOMAIN

RELAY_TYPES = {6946, 6753}
TYPES = {1889: "Датчик температуры", 385: "Аналоговый датчик", 321: "Аккумулятор",
         737: "Наличие питания 220 В", 6946: "Реле электромагнитное", 6753: "Выход управления",
         14722: "Эктоконтроль 3.2"}

def lk(device):
    return device.get("lk") or device.get("state", {}).get("lk") or {}

def reading(device, path):
    value = device
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return None if isinstance(value, (dict, list)) or value in (32767, 3276.7) else value

def connected(device):
    status = device.get("system_connection_status")
    if status is None:
        status = device.get("connection")
    return status is not False and reading(device, "state.state.val") != 255

def validate_switch(device, value):
    if not device or int(device.get("cloud_type", 0)) not in RELAY_TYPES or value not in (0, 1):
        raise HomeAssistantError("Управление этим типом оборудования пока не поддерживается")
    if not connected(device):
        raise HomeAssistantError("Нет связи с оборудованием")
    if lk(device).get("control_locked"):
        raise HomeAssistantError("Оборудованием управляет программа. Используйте управление программой.")

def discover(coordinator, entry, async_add_entities, platform):
    known = set()
    def add_new():
        entities = []
        for object_id, device in coordinator.data.get("equipment", {}).items():
            if object_id == coordinator.ids[0]:
                continue  # Existing boiler entities retain their identifiers.
            if platform == "switch":
                fields = ["switch"] if int(device.get("cloud_type", 0)) in RELAY_TYPES else []
            else:
                fields = ["status", "connection"]
                if "value" in device.get("state", {}):
                    fields.append("value")
                if "quality" in device.get("state", {}).get("power", {}):
                    fields.append("quality")
            for field in fields:
                key = (object_id, field)
                if key in known:
                    continue
                known.add(key)
                cls = EquipmentSwitch if field == "switch" else EquipmentSensor
                entities.append(cls(coordinator, entry, object_id, field))
        if entities:
            async_add_entities(entities)
    entry.async_on_unload(coordinator.async_add_listener(add_new))
    add_new()

class EquipmentEntity(CoordinatorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, entry, object_id, field):
        super().__init__(coordinator)
        self.object_id, self.field = object_id, field
        self._attr_unique_id = f"{entry.entry_id}_equipment_{object_id}_{field}"
        self._attr_name = {"status": "Состояние", "connection": "Связь", "value": "Показание",
                           "quality": "Качество питания датчика", "switch": "Управление"}[field]
    @property
    def device(self):
        return self.coordinator.data.get("equipment", {}).get(self.object_id, {})
    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, f"equipment_{self.object_id}")},
                "name": self.device.get("config", {}).get("name", f"Оборудование {self.object_id}"),
                "manufacturer": "Ectostroy",
                "model": TYPES.get(int(self.device.get("cloud_type", 0)), f"Тип {self.device.get('cloud_type')}"),
                "configuration_url": f"https://my.ectostroy.ru/#equipment/{self.object_id}"}
    @property
    def available(self):
        return super().available and bool(self.device)

class EquipmentSensor(EquipmentEntity, SensorEntity):
    def __init__(self, *args):
        super().__init__(*args)
        if self.field == "value" and self.device.get("cloud_type") == 1889:
            self._attr_native_unit_of_measurement = "°C"
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
        elif self.field == "value" and self.device.get("cloud_type") != 737:
            self._attr_native_unit_of_measurement = self.device.get("config", {}).get("unit") or ("%" if self.device.get("cloud_type") == 321 else None)
    @property
    def native_value(self):
        if self.field == "status":
            return lk(self.device).get("state_name")
        if self.field == "connection":
            return "Есть" if connected(self.device) else "Нет"
        if self.field == "quality":
            return reading(self.device, "state.power.quality")
        value = reading(self.device, "state.value.val")
        if self.device.get("cloud_type") == 737:
            return None if value is None else "Есть" if value else "Нет"
        return value if connected(self.device) else None
    @property
    def extra_state_attributes(self):
        return {"object_id": self.object_id, "cloud_type": self.device.get("cloud_type"),
                "control_locked": bool(lk(self.device).get("control_locked")),
                "controlling_program": (lk(self.device).get("under_control") or {}).get("name")}

class EquipmentSwitch(EquipmentEntity, SwitchEntity):
    @property
    def is_on(self):
        value = reading(self.device, "state.state.val")
        return None if value not in (0, 1) else bool(value)
    @property
    def available(self):
        return super().available and connected(self.device) and not lk(self.device).get("control_locked", False)
    async def async_turn_on(self, **kwargs):
        await self.coordinator.set_equipment(self.object_id, 1)
    async def async_turn_off(self, **kwargs):
        await self.coordinator.set_equipment(self.object_id, 0)
