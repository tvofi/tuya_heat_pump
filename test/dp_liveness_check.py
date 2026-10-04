"""Standalone behavioral check for DP "liveness" in the tuya_heat_pump
integration (entities surviving a cloud shadow / status frame that drops
data points the device has not re-reported lately).

Runs completely outside Home Assistant: homeassistant.*, tinytuya and
requests are stubbed, and the real integration modules are loaded from
disk. Exercises the code paths added for the Rotenso Windmi dp 110
night_mode incident (last reported 2026-06-20, fallen out of the Tuya
cloud shadow by Oct 2026: toggle gone from the Tuya app, switch
unavailable in HA):

  - coordinator.dp_known(): which DPs the device's own schema vouches for
  - entity availability: schema-known DP missing from poll data →
    available + "unknown" state instead of unavailable
  - platform setup: sensors / binary sensors are still CREATED when the
    first poll lacks a schema-known DP (previously skipped forever)
  - coordinator._optimistic_update(): an accepted write inserts/updates
    the code in coordinator.data immediately
  - diagnostics._mapped_but_not_reported(): lists entity-mapped codes the
    device has not reported
  - null controls: no data, no schema, no dp_id, None configs

Usage:
    python3 test/dp_liveness_check.py [path/to/custom_components/tuya_heat_pump]

    The path defaults to the integration directory that ships next to
    this script. Point it at a (mutated) copy to use it as a mutation
    killer. Exit code 0 = all checks passed.
"""
from __future__ import annotations

import asyncio
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Minimal stub environment: fabricate homeassistant.* / tinytuya / requests
# so the integration modules import on a machine without HA installed.
# ---------------------------------------------------------------------------
class _NS:
    """Any attribute you ask for, fabricated recursively."""

    def __getattr__(self, name):
        value = _NS()
        object.__setattr__(self, name, value)
        return value


class _Loader(importlib.abc.Loader):
    def create_module(self, spec):
        return sys.modules[spec.name]

    def exec_module(self, module):
        pass


class _HAFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("homeassistant"):
            return None
        module = types.ModuleType(fullname)
        module.__path__ = []

        def fabricate(name, _module=module):
            value = _NS()
            setattr(_module, name, value)
            return value

        module.__getattr__ = fabricate
        sys.modules[fullname] = module
        return importlib.machinery.ModuleSpec(fullname, _Loader(), is_package=True)


def _install_stubs():
    sys.meta_path.insert(0, _HAFinder())

    def base():
        class B:
            pass
        return B

    import homeassistant.components.switch as m
    m.SwitchEntity = base()
    import homeassistant.components.sensor as m
    m.SensorEntity = base()
    import homeassistant.components.binary_sensor as m
    m.BinarySensorEntity = base()
    import homeassistant.components.number as m
    m.NumberEntity = base()
    m.NumberMode = _NS()
    import homeassistant.components.select as m
    m.SelectEntity = base()
    import homeassistant.components.text as m
    m.TextEntity = base()
    import homeassistant.helpers.restore_state as m
    m.RestoreEntity = base()
    import homeassistant.helpers.update_coordinator as m
    m.DataUpdateCoordinator = object
    m.UpdateFailed = type("UpdateFailed", (Exception,), {})
    import homeassistant.exceptions as m
    m.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    m.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    m.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
    import homeassistant.helpers.entity as m
    m.EntityCategory = ec = _NS()
    ec.CONFIG = "config"
    ec.DIAGNOSTIC = "diagnostic"
    import homeassistant.components.diagnostics as m
    m.async_redact_data = lambda data, to_redact: data
    import homeassistant.core as m
    m.HomeAssistant = object
    import homeassistant.helpers.entity_platform as m
    m.AddEntitiesCallback = object
    import homeassistant.config_entries as m
    m.ConfigEntry = object

    for name in ("tinytuya", "requests"):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            if name == "requests":
                stub.exceptions = types.SimpleNamespace(
                    Timeout=type("Timeout", (Exception,), {}),
                    RequestException=type("RequestException", (Exception,), {}),
                )
            sys.modules[name] = stub


def _load_integration(integration_dir: Path):
    pkg = types.ModuleType("tuya_heat_pump")
    pkg.__path__ = [str(integration_dir)]
    sys.modules["tuya_heat_pump"] = pkg

    def load(sub):
        spec = importlib.util.spec_from_file_location(
            f"tuya_heat_pump.{sub}", integration_dir / f"{sub}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"tuya_heat_pump.{sub}"] = module
        spec.loader.exec_module(module)
        return module

    for sub in ("const", "conversion", "raw_codec", "entity_helpers",
                "model_loader", "discovery"):
        load(sub)
    return {
        "switch": load("switch"),
        "sensor": load("sensor"),
        "binary_sensor": load("binary_sensor"),
        "number": load("number"),
        "select": load("select"),
        "coordinator": load("coordinator"),
        "diagnostics": load("diagnostics"),
    }


# ---------------------------------------------------------------------------
# Fixtures: a coordinator with real methods and stubbed state.
# ---------------------------------------------------------------------------
SCHEMA = {
    dp: {"dp_id": dp, "code": code, "access": access, "type": dp_type}
    for dp, code, access, dp_type in [
        (1, "switch", "rw", "bool"),
        (2, "mode", "rw", "enum"),
        (9, "temp_set", "rw", "value"),
        (10, "temp_current", "ro", "value"),
        (16, "timer", "rw", "raw"),
        (20, "fault", "ro", "bitmap"),
        (110, "night_mode", "rw", "bool"),
        (114, "Tw2", "ro", "value"),
        (116, "T1B", "ro", "value"),
    ]
}

CFG_110 = {
    "dp_id": 110, "code": "night_mode", "name": "Night Mode (Silent)",
    "icon": "mdi:weather-night",
    "conversion": "value in [1, True, '1', 'true', 'on', 'yes', 'enable', 'open']",
}

MODEL = {
    "sensors": {
        "temp_current": {"dp_id": 10, "code": "temp_current", "name": "Outlet",
                         "device_class": "temperature", "state_class": "measurement"},
        "Tw2": {"dp_id": 114, "code": "Tw2", "name": "Zone2",
                "device_class": "temperature",
                "conversion": "value if value > -30 else None"},
        "water_delta_t": {"name": "ΔT", "formula": "1"},
    },
    "binary_sensors": {
        "fault": {"dp_id": 20, "code": "fault", "name": "Fault",
                  "device_class": "problem"},
    },
    "switches": {"night_mode": dict(CFG_110)},
}


def make_coord(Coord, data=None, schema=SCHEMA, ok=True):
    coordinator = object.__new__(Coord)
    coordinator.last_update_success = ok
    coordinator.data = data
    coordinator.device_schema = schema
    coordinator.dp_mapping = {dp: prop["code"] for dp, prop in (schema or {}).items()}
    coordinator.device_name = "heat pump"
    coordinator.device_info = None
    coordinator.model_id = "000004k4z6"
    coordinator.model_mapping = MODEL
    return coordinator


def run_setup(module, coordinator):
    made = []

    def add(entities):  # HA's async_add_entities is called synchronously
        made.extend(entities)

    hass = types.SimpleNamespace(data={"tuya_heat_pump": {"e1": coordinator}})
    entry = types.SimpleNamespace(entry_id="e1")
    asyncio.run(module.async_setup_entry(hass, entry, add))
    return made


# ---------------------------------------------------------------------------
# The checks. Each returns (name, ok, detail).
# ---------------------------------------------------------------------------
def check_all(mods):
    Coord = mods["coordinator"].TuyaScaleDataUpdateCoordinator
    results = []

    def record(name, condition, detail=""):
        results.append((name, bool(condition), detail))

    # ---- dp_known ----------------------------------------------------------
    co = make_coord(Coord, data={"switch": {"value": True}})  # night_mode missing
    record("dp_known: schema-rw DP", co.dp_known({"dp_id": 110, "code": "night_mode"}) is True)
    record("dp_known: schema-ro DP", co.dp_known({"dp_id": 10}) is True)
    record("dp_known: unknown dp_id", co.dp_known({"dp_id": 999}) is False)
    record("dp_known: no dp_id", co.dp_known({"code": "night_mode"}) is False)
    record("dp_known: raw-field excluded", co.dp_known({"dp_id": 16, "field_index": 2}) is False)
    record("dp_known: empty schema → old behavior",
           make_coord(Coord, schema={}).dp_known({"dp_id": 110}) is False)

    # null controls
    record("dp_known: config=None", make_coord(Coord).dp_known(None) is False)
    record("dp_known: schema=None", make_coord(Coord, schema=None).dp_known({"dp_id": 110}) is False)

    # ---- switch ------------------------------------------------------------
    switch_py = mods["switch"]
    sw = switch_py.TuyaHeatpumpSwitch(make_coord(Coord, data={}), "night_mode", CFG_110)
    record("switch: schema-known missing DP → available, unknown",
           sw.available is True and sw.is_on is None)
    record("switch: no schema → unavailable",
           switch_py.TuyaHeatpumpSwitch(make_coord(Coord, data={}, schema={}),
                                        "night_mode", CFG_110).available is False)
    record("switch: failed poll → unavailable",
           switch_py.TuyaHeatpumpSwitch(make_coord(Coord, data={}, ok=False),
                                        "night_mode", CFG_110).available is False)
    record("switch: null data → unavailable",
           switch_py.TuyaHeatpumpSwitch(make_coord(Coord, data=None),
                                        "night_mode", CFG_110).available is False)
    sw4 = switch_py.TuyaHeatpumpSwitch(make_coord(Coord, data={"night_mode": {"value": True}}),
                                       "night_mode", CFG_110)
    record("switch: data present → regression-free",
           sw4.available is True and sw4.is_on is True)

    # ---- setup-time creation (sensor + binary sensor) ----------------------
    co = make_coord(Coord, data={"switch": {"value": True},
                                 "temp_current": {"value": 36}})
    sensors = run_setup(mods["sensor"], co)
    codes = {getattr(s, "_sensor_code", None) for s in sensors}
    record("setup: schema-known sensor created despite missing data",
           {"temp_current", "Tw2", "water_delta_t"} <= codes, str(sorted(codes)))
    bsensors = run_setup(mods["binary_sensor"], co)
    bcodes = {getattr(b, "_sensor_code", None) for b in bsensors}
    record("setup: schema-known binary sensor created despite missing data",
           "fault" in bcodes and any(type(b).__name__ == "TuyaHeatpumpOnlineSensor"
                                     for b in bsensors), str(sorted(map(str, bcodes))))

    co2 = make_coord(Coord, data={"switch": {"value": True}})
    co2.model_mapping = {"sensors": {"ghost": {"dp_id": 999, "code": "ghost", "name": "Ghost"}}}
    made = run_setup(mods["sensor"], co2)
    record("setup: unknown DP still skipped (old guard kept)",
           "ghost" not in {getattr(s, "_sensor_code", None) for s in made})

    # ---- availability across platforms --------------------------------------
    co3 = make_coord(Coord, data={})  # everything missing, schema known
    number_entity = mods["number"].TuyaHeatpumpNumber(
        co3, "temp_set", {"dp_id": 9, "code": "temp_set", "name": "Setpoint",
                          "min_value": 5, "max_value": 65, "step": 1})
    record("number: available + unknown when schema-known DP missing",
           number_entity.available is True and number_entity.native_value is None)
    select_entity = mods["select"].TuyaHeatpumpSelect(
        co3, "mode", {"dp_id": 2, "code": "mode", "name": "Mode",
                      "options": {"heat": "Heating"}})
    record("select: available + unknown when schema-known DP missing",
           select_entity.available is True and select_entity.current_option is None)
    for s in sensors:
        if getattr(s, "_sensor_code", None) == "Tw2":
            record("sensor: available + unknown when schema-known DP missing",
                   s.available is True and s.native_value is None)
    for b in bsensors:
        if getattr(b, "_sensor_code", None) == "fault":
            record("binary_sensor: available + unknown when schema-known DP missing",
                   b.available is True and b.is_on is None)

    # formula sensor availability is coordinator-success only (unchanged)
    for s in sensors:
        if getattr(s, "_sensor_code", None) == "water_delta_t":
            record("sensor: formula availability unchanged", s.available is True)
    bad = mods["sensor"].TuyaHeatpumpSensor(
        make_coord(Coord, data=None, ok=False), "water_delta_t",
        MODEL["sensors"]["water_delta_t"])
    record("sensor: failed poll → unavailable (formula)", bad.available is False)

    # ---- _optimistic_update --------------------------------------------------
    stub = types.SimpleNamespace(
        data={"switch": {"value": True, "timestamp": 1, "type": "bool", "dp_id": 1}},
        get_dp_id=lambda code: 110 if code == "night_mode" else None,
        async_update_listeners=lambda: None)
    Coord._optimistic_update(stub, "night_mode", False)
    entry = stub.data.get("night_mode")
    record("optimistic: absent code inserted",
           bool(entry) and entry["value"] is False and entry["dp_id"] == 110
           and entry["timestamp"] >= 1)
    old_ts = stub.data["switch"]["timestamp"]
    Coord._optimistic_update(stub, "switch", False)
    updated = stub.data["switch"]
    record("optimistic: existing entry updated, keys preserved",
           updated["value"] is False and updated["type"] == "bool"
           and updated["dp_id"] == 1 and updated["timestamp"] >= old_ts
           and set(updated) == {"value", "timestamp", "type", "dp_id"},
           str(updated))
    stub2 = types.SimpleNamespace(data=None, get_dp_id=lambda c: None,
                                  async_update_listeners=lambda: None)
    Coord._optimistic_update(stub2, "night_mode", True)
    record("optimistic: null data tolerated", stub2.data is None)

    # ---- diagnostics ----------------------------------------------------------
    mapping = {
        "switches": {"night_mode": {"dp_id": 110, "code": "night_mode"},
                     "switch": {"dp_id": 1, "code": "switch"}},
        "sensors": {"water_delta_t": {"code": "water_delta_t", "formula": "Tout - Tin"},
                    "timer_raw": {"dp_id": 16, "code": "timer", "raw_source": "timer"}},
    }
    out = mods["diagnostics"]._mapped_but_not_reported(mapping, {"switch": {"value": True}})
    record("diagnostics: mapped-but-not-reported listed", out == ["night_mode", "timer"], str(out))
    out2 = mods["diagnostics"]._mapped_but_not_reported(None, {})
    record("diagnostics: null mapping tolerated", out2 == [])

    # ---- regressions of earlier beta features --------------------------------
    # beta05 (PR #5): temperature calibration offset numbers are created for
    # every temperature sensor and write nothing to the device.
    numbers = run_setup(mods["number"], make_coord(Coord, data={"switch": {"value": True}}))
    calib = [x for x in numbers if type(x).__name__ == "TuyaHeatpumpCalibrationNumber"]
    record("regression beta05: calibration numbers still created",
           len(calib) >= 2, f"{len(calib)} calibration entities")

    # beta06 (PR #6): water set-point minimum is raised per operating mode.
    co_mode = make_coord(Coord, data={"mode": {"value": "DHW"}, "temp_set": {"value": 40}})
    sp = mods["number"].TuyaHeatpumpNumber(
        co_mode, "temp_set",
        {"dp_id": 9, "code": "temp_set", "name": "Setpoint",
         "min_value": 5.0, "min_value_by_mode": {"heat": 25.0, "DHW": 25.0},
         "max_value": 65.0, "step": 1})
    record("regression beta06: min-by-mode raised while heating",
           sp.native_min_value == 25.0, str(sp.native_min_value))
    co_nomode = make_coord(Coord, data={"temp_set": {"value": 40}})
    sp2 = mods["number"].TuyaHeatpumpNumber(
        co_nomode, "temp_set",
        {"dp_id": 9, "code": "temp_set", "name": "Setpoint",
         "min_value": 5.0, "min_value_by_mode": {"heat": 25.0, "DHW": 25.0},
         "max_value": 65.0, "step": 1})
    record("regression beta06: plain minimum without mode",
           sp2.native_min_value == 5.0, str(sp2.native_min_value))
    co_nullmode = make_coord(Coord, data={})
    sp3 = mods["number"].TuyaHeatpumpNumber(
        co_nullmode, "temp_set",
        {"dp_id": 9, "code": "temp_set", "name": "Setpoint",
         "min_value": 5.0, "min_value_by_mode": {"heat": 25.0}, "max_value": 65.0,
         "step": 1})
    record("regression beta06: null-control, no data at all",
           sp3.native_min_value == 5.0, str(sp3.native_min_value))

    # beta05 (PR #5): the calibration offset still applies to readings.
    co5 = make_coord(Coord, data={"temp_current": {"value": 36}})
    sens = mods["sensor"].TuyaHeatpumpSensor(co5, "temp_current",
                                             MODEL["sensors"]["temp_current"])
    co5.set_sensor_offset = lambda code, offset: None
    co5._sensor_offsets = {"temp_current": 0.7}
    record("regression beta05: sensor offset still applied",
           sens.native_value == 36.7, str(sens.native_value))

    return results


def main() -> int:
    default_dir = Path(__file__).resolve().parent.parent / "custom_components" / "tuya_heat_pump"
    integration_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir
    if not (integration_dir / "coordinator.py").exists():
        print(f"integration directory not found: {integration_dir}")
        return 2

    _install_stubs()
    mods = _load_integration(integration_dir)
    results = check_all(mods)

    failed = 0
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        suffix = f"  [{detail}]" if detail and not ok else ""
        print(f"{status}  {name}{suffix}")
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
