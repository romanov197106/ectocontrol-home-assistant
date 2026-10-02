"""Read-only boiler telemetry and program settings."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import DOMAIN

# Object, path, Russian label, optional unit. Zero values remain valid.
FIELDS = [
    ("boiler", "state.lk.under_control.name", "Управляющая программа котла", None),
    ("boiler", "config.boiler_model", "Модель котла", None),
    ("boiler", "config.pza", "Погодозависимая автоматика", None),
    ("boiler", "state.pot_sta", "Служебный статус адаптера", None),
    ("boiler", "state.pot_error_state", "Ошибка связи адаптера", None),
    ("boiler", "state.hot_water_supply_expense", "Расход ГВС", "L/min"),
    ("boiler", "config.sensor_environment.state.value.val", "Температура улицы", "°C"),
    ("boiler", "config.sensor_room.state.value.val", "Комнатный датчик адаптера", "°C"),
    ("boiler", "system_connection_status", "Связь системы с сервером", None),
    ("boiler", "state.pot_link_to_boiler", "Связь адаптера с котлом", None),
    ("boiler", "state.link_to_system", "Связь адаптера с системой", None),
    ("boiler", "state.ebus_flag", "Протокол eBUS", None),
    ("boiler", "state.channel_2", "Нагрев второго контура", None),
    ("boiler", "state.waiting", "Ожидание котла", None),
    ("boiler", "state.error_code", "Код ошибки котла", None),
    ("boiler", "state.diagnostic_code", "Диагностический код котла", None),
    ("boiler", "state.error_state", "Ошибка котла", None),
    ("boiler", "state.error_ignition", "Ошибка розжига", None),
    ("boiler", "state.error_overheat", "Ошибка перегрева", None),
    ("boiler", "state.error_ventilation", "Ошибка вентиляции", None),
    ("boiler", "state.error_water_press", "Ошибка давления воды", None),
    ("boiler", "error_description.status", "Авария адаптера", None),
    ("boiler", "config.hysteresis", "Гистерезис адаптера", "°C"),
    ("boiler", "state.coolant_temperature", "Температура теплоносителя", "°C"),
    ("boiler", "state.hot_water_supply_temperature", "Температура ГВС", "°C"),
    ("boiler", "state.pressure", "Давление", "bar"),
    ("boiler", "state.flame_mode", "Модуляция горелки", "%"),
    ("boiler", "state.flame", "Горелка", None),
    ("boiler", "state.channel_1", "Нагрев отопления", None),
    ("boiler", "state.heat_water", "Нагрев ГВС", None),
    ("boiler", "lk.state_name", "Состояние адаптера", None),
    ("boiler", "config.set_channel_1_temperature", "Уставка теплоносителя", "°C"),
    ("boiler", "config.set_heat_water_temperature", "Уставка ГВС", "°C"),
    ("boiler", "config.room_setpoint", "Уставка комнаты котла", "°C"),
    ("boiler", "config.pza_curve_number", "Кривая ПЗА", None),
    ("program", "lk.state_name", "Состояние программы", None),
    ("program", "config.pau_therm_value", "Целевая температура", "°C"),
    ("program", "config.sensor_temperature.state.value.val", "Температура комнаты", "°C"),
    ("program", "config.flags.active", "Ручной режим", None),
    ("program", "config.flags.control_from_schedule", "Управление расписанием", None),
    ("program", "config.pau_therm_pre_eco", "Температура Эконом", "°C"),
    ("program", "config.pau_therm_pre_std", "Температура Стандарт", "°C"),
    ("program", "config.pau_therm_pre_comf", "Температура Комфорт", "°C"),
    ("program", "config.pau_therm_pre_usr", "Своя температура", "°C"),
    ("program", "config.pau_therm_hyst", "Гистерезис", "°C"),
    ("program", "config.pau_therm_del_pump", "Выбег насоса", None),
]

def lookup(data, obj, path):
    value = data.get(obj, {})
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value in (32767, 3276.7) or isinstance(value, (dict, list)):
        return None
    return value

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    from .programs import discover
    discover(coordinator, entry, async_add_entities, "sensor")
    from .equipment import discover as discover_equipment
    discover_equipment(coordinator, entry, async_add_entities, "sensor")
    known = set()
    def add_new():
        entities = []
        for field in FIELDS:
            key = field[:2]
            if key not in known and lookup(coordinator.data, *key) is not None:
                known.add(key)
                entities.append(Telemetry(coordinator, entry, *field))
        if entities:
            async_add_entities(entities)
    entry.async_on_unload(coordinator.async_add_listener(add_new))
    add_new()

class Telemetry(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, obj, path, name, unit):
        super().__init__(coordinator)
        self.obj, self.path = obj, path
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{obj}_{path}"
        self._attr_native_unit_of_measurement = unit
        if unit == "°C":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
        elif unit == "bar":
            self._attr_device_class = SensorDeviceClass.PRESSURE
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.data['boiler_id']}_{entry.data['program_id']}")},
            "name": "Котёл и программа Эктоконтроль",
            "manufacturer": "Ectostroy", "model": "Облачное чтение eBUS/OpenTherm",
            "configuration_url": f"https://my.ectostroy.ru/#program/{entry.data['program_id']}",
        }

    @property
    def native_value(self):
        value = lookup(self.coordinator.data, self.obj, self.path)
        if self.path == "config.boiler_model":
            return self.coordinator.data.get("boiler", {}).get("allowed_boiler_models", {}).get(str(value), value)
        # Cabinet flags.active=1 means automatic program, manual switch is off.
        if self.path == "config.flags.active":
            return None if value is None else ("Нет" if value else "Да")
        if self.path in {"state.flame", "state.channel_1", "state.heat_water",
                          "config.flags.active", "config.flags.control_from_schedule",
                          "system_connection_status", "state.pot_link_to_boiler", "state.link_to_system",
                          "state.ebus_flag", "state.channel_2", "state.waiting", "state.error_state",
                          "state.error_ignition", "state.error_overheat", "state.error_ventilation",
                          "state.error_water_press", "error_description.status", "config.pza", "state.pot_error_state"}:
            return None if value is None else ("Да" if value else "Нет")
        return value

    @property
    def available(self):
        return super().available and lookup(self.coordinator.data, self.obj, self.path) is not None
