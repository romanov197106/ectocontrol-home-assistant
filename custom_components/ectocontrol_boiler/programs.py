"""Discovery and explicitly supported cabinet program commands."""
import math
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import DOMAIN

ROUTES = {
    -1: "task/send_opentherm_program_3x_system",
    32770: "task/send_heating_program_3x_system",
    32769: "task/send_security_program_3x_system",
    32768: "task/send_notification_program_3x_system",
    32771: "task/send_reaction_on_sensors_program_3x_system",
    32772: "task/send_shcedule_program_3x_system",
}
MODE = {"Вручную": 0, "Автоматически": 1}
ALIVE = {"Нет оповещений": 0, **{f"Раз в {n} дн.": n for n in range(1, 7)}, "Раз в неделю": 7, "Дважды в день": 9}
RECALL = {"Не перезванивать": 0, **{f"Повторов: {n}": n for n in range(1, 6)}}
LIMIT_PAIRS = [("channel_1_min_temperature", "channel_1_max_temperature"),
               ("heat_water_min_temperature", "heat_water_max_temperature"),
               ("press_min", "press_max")]
# platform, field, label, config path, options or numerical range
SPECS = {
    -1: [
        *[("number", field, label, field, bounds) for field, label, bounds in [
            ("channel_1_min_temperature", "Минимальная температура отопления", (0, 100, 1)),
            ("channel_1_max_temperature", "Максимальная температура отопления", (0, 100, 1)),
            ("heat_water_min_temperature", "Минимальная температура ГВС", (0, 100, 1)),
            ("heat_water_max_temperature", "Максимальная температура ГВС", (0, 100, 1)),
            ("press_min", "Минимальное давление", (0.1, 5, 0.1)),
            ("press_max", "Максимальное давление", (0.1, 5, 0.1)),
            ("flame", "Максимальная мощность горелки", (0, 100, 1)),
            ("crash_temperature", "Температура при аварии", (0, 100, 1)),
            ("pza_curve_number", "Номер кривой ПЗА", (1, 16, 1)),
        ]],
        ("switch", "channel_2_status", "Разрешение второго контура", "channel_2_status", None),
        ("switch", "log", "Журнал адаптера", "log", None),
        ("switch", "bypass_mode", "Байпас адаптера", "bypass_mode", None),
        ("number", "set_channel_1_temperature", "Уставка отопления котла", "set_channel_1_temperature", (0, 100, 1)),
        ("number", "set_heat_water_temperature", "Уставка ГВС котла", "set_heat_water_temperature", (0, 100, 1)),
        ("number", "room_setpoint", "Комнатная уставка котла", "room_setpoint", (5, 35, 0.1)),
        ("switch", "channel_1_status", "Разрешение отопления котла", "channel_1_status", None),
        ("switch", "heat_water", "Разрешение ГВС котла", "heat_water", None),
    ],
    32770: [
        ("select", "active", "Режим программы", "flags.active", MODE),
        ("switch", "control_from_schedule", "Управление расписанием", "flags.control_from_schedule", None),
        *[("number", field, label, field, (5, 35, 0.1)) for field, label in [
            ("pau_therm_value", "Целевая температура"),
            ("pau_therm_pre_eco", "Температура Эконом"),
            ("pau_therm_pre_std", "Температура Стандарт"),
            ("pau_therm_pre_comf", "Температура Комфорт"),
            ("pau_therm_pre_usr", "Своя температура")]],
    ],
    32769: [("switch", "security_active", "Охрана", "flags.security_active", None),
            ("switch", "notif_arm_disarm", "Уведомлять о постановке и снятии", "notif_arm_disarm", None)],
    32768: [("switch", "cfg_gnotif", "Оповещения системы", "cfg_gnotif", None),
            ("switch", "cfg_retnorm", "Оповещать об окончании тревоги", "cfg_retnorm", None),
            ("select", "cfg_alive", "Периодические сообщения", "cfg_alive", ALIVE),
            ("select", "cfg_recal", "Повторные звонки", "cfg_recal", RECALL)],
    32771: [("select", "active", "Режим программы", "flags.active", MODE)],
    32772: [("select", "active", "Режим программы", "flags.active", MODE)],
}

def get_value(program, path):
    value = program.get("config", {})
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value

def validate_command(program, field, value):
    kind = int(program.get("cloud_type", 0))
    spec = next((s for s in SPECS.get(kind, []) if s[1] == field), None)
    if spec is None or get_value(program, spec[3]) is None:
        raise HomeAssistantError("Этот параметр программы не поддерживается")
    if spec[0] == "number":
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not spec[4][0] <= value <= spec[4][1]:
            raise HomeAssistantError("Температура вне допустимого диапазона")
        if spec[4][2] == 1 and value != int(value):
            raise HomeAssistantError("Укажите целое значение")
        if kind == -1:
            for low_field, high_field in LIMIT_PAIRS:
                if field in (low_field, high_field):
                    low = value if field == low_field else get_value(program, low_field)
                    high = value if field == high_field else get_value(program, high_field)
                    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)) or low > high:
                        raise HomeAssistantError("Минимум должен быть не выше максимума")
            prefix = {"set_channel_1_temperature": "channel_1", "set_heat_water_temperature": "heat_water"}.get(field)
            if prefix:
                config = program.get("config", {})
                low, high = config.get(prefix + "_min_temperature"), config.get(prefix + "_max_temperature")
                if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low <= high and not low <= value <= high:
                    raise HomeAssistantError("Уставка вне ограничений, заданных в кабинете котла")
    elif spec[0] == "select":
        if value not in spec[4].values():
            raise HomeAssistantError("Недопустимый режим")
    elif value not in (0, 1):
        raise HomeAssistantError("Недопустимое состояние")
    if field == "security_active" and value and program.get("lk", {}).get("state_name") == "Не настроена":
        raise HomeAssistantError("Сначала настройте программу охраны в личном кабинете")

def discover(coordinator, entry, async_add_entities, platform):
    """Run on every refresh, including programs created after HA startup."""
    known = set()
    def add_new():
        entities = []
        objects = dict(coordinator.data.get("programs", {}))
        if platform in {"number", "switch"} and hasattr(coordinator, "ids"):
            objects[coordinator.ids[0]] = dict(coordinator.data.get("boiler", {}), cloud_type=-1)
        for object_id, program in objects.items():
            specs = [("sensor", "status", "Состояние", "", None)] if platform == "sensor" else SPECS.get(int(program.get("cloud_type", 0)), [])
            for spec in specs:
                key = (object_id, spec[1])
                if spec[0] != platform or key in known:
                    continue
                if platform != "sensor" and (get_value(program, spec[3]) is None or get_value(program, spec[3]) in (32767, 3276.7)):
                    continue
                known.add(key)
                cls = {"sensor": ProgramStatus, "number": ProgramNumber, "switch": ProgramSwitch, "select": ProgramSelect}[platform]
                entities.append(cls(coordinator, entry, object_id, spec))
        if entities:
            async_add_entities(entities)
    entry.async_on_unload(coordinator.async_add_listener(add_new))
    add_new()

class ProgramEntity(CoordinatorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, entry, object_id, spec):
        super().__init__(coordinator)
        self.object_id, self.spec = object_id, spec
        self._attr_name = spec[2]
        self._attr_unique_id = f"{entry.entry_id}_program_{object_id}_{spec[1]}"
    @property
    def program(self):
        if hasattr(self.coordinator, "ids") and self.object_id == self.coordinator.ids[0]:
            return dict(self.coordinator.data.get("boiler", {}), cloud_type=-1)
        return self.coordinator.data.get("programs", {}).get(self.object_id, {})
    @property
    def device_info(self):
        if self.program.get("cloud_type") == -1:
            return {"identifiers": {(DOMAIN, f"{self.coordinator.ids[0]}_{self.coordinator.ids[1]}")},
                    "name": "Котёл и программа Эктоконтроль", "manufacturer": "Ectostroy",
                    "model": "Облачное чтение eBUS/OpenTherm"}
        return {"identifiers": {(DOMAIN, f"program_{self.object_id}")},
                "name": self.program.get("config", {}).get("name", f"Программа {self.object_id}"),
                "manufacturer": "Ectostroy", "model": "Программа Эктоконтроль",
                "configuration_url": f"https://my.ectostroy.ru/#program/{self.object_id}"}
    @property
    def available(self):
        return super().available and bool(self.program) and (self.spec[0] == "sensor" or get_value(self.program, self.spec[3]) is not None)
    async def send(self, value):
        if self.program.get("cloud_type") == -1:
            await self.coordinator.set_boiler(self.spec[1], value)
        else:
            await self.coordinator.set_program(self.object_id, self.spec[1], value)

class ProgramStatus(ProgramEntity, SensorEntity):
    @property
    def native_value(self):
        return self.program.get("lk", {}).get("state_name")
    @property
    def extra_state_attributes(self):
        return {"program_id": self.object_id, "program_type": self.program.get("cloud_type"),
                "control_supported": int(self.program.get("cloud_type", 0)) in SPECS}

class ProgramNumber(ProgramEntity, NumberEntity):
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = "box"
    def __init__(self, *args):
        super().__init__(*args)
        self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = self.spec[4]
        if self.program.get("cloud_type") == -1:
            field = self.spec[1]
            self._attr_native_unit_of_measurement = "bar" if field.startswith("press_") else "%" if field == "flame" else None if field == "pza_curve_number" else "°C"
    @property
    def native_value(self):
        return get_value(self.program, self.spec[3])
    async def async_set_native_value(self, value):
        await self.send(value)

class ProgramSwitch(ProgramEntity, SwitchEntity):
    @property
    def is_on(self):
        return bool(get_value(self.program, self.spec[3]))
    async def async_turn_on(self, **kwargs):
        await self.send(1)
    async def async_turn_off(self, **kwargs):
        await self.send(0)

class ProgramSelect(ProgramEntity, SelectEntity):
    @property
    def options(self):
        return list(self.spec[4])
    @property
    def current_option(self):
        value = get_value(self.program, self.spec[3])
        return next((label for label, code in self.spec[4].items() if code == value), None)
    async def async_select_option(self, option):
        if option not in self.spec[4]:
            raise HomeAssistantError("Недопустимый выбор")
        await self.send(self.spec[4][option])
