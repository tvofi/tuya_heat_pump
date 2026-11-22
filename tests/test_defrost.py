"""Defrost state: heuristic, option-entity override, Windmi model wiring,
entity migration and the options step.

All values are invented. Every positive case has a null control that
differs in the one input the behaviour depends on.

Needs Home Assistant installed; run from the repo root:
python -m pytest tests
"""
import asyncio
import importlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

if os.environ.get("TUYA_HP_REQUIRE_HA"):
    import homeassistant  # noqa: F401  CI: a broken HA import must fail, not skip
else:
    pytest.importorskip("homeassistant")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PKG = "custom_components.tuya_heat_pump"
importlib.import_module(PKG)
defrost = importlib.import_module(f"{PKG}.defrost")
coordinator_mod = importlib.import_module(f"{PKG}.coordinator")
sensor_mod = importlib.import_module(f"{PKG}.sensor")
binary_mod = importlib.import_module(f"{PKG}.binary_sensor")
flow_mod = importlib.import_module(f"{PKG}.config_flow")
const = importlib.import_module(f"{PKG}.const")
windmi = importlib.import_module(f"{PKG}.models.000004k4z6")
C = coordinator_mod.TuyaScaleDataUpdateCoordinator

CFG = {
    "mode": "mode",
    "heating_modes": ["heat", "HEATDHW", "DHW"],
    "supply": "Tout",
    "return": "Tin",
    "confirm": ["T3", "T4"],
}


def feed(detector, samples, spacing=60.0):
    """Feed dict samples (code -> value) at fixed spacing; return states."""
    out = []
    for i, values in enumerate(samples):
        out.append(detector.update(values.get, now=i * spacing))
    return out


def s(mode="heat", tout=30.0, tin=33.0, t3=None, t4=None):
    values = {"mode": mode, "Tout": tout, "Tin": tin}
    if t3 is not None:
        values["T3"] = t3
    if t4 is not None:
        values["T4"] = t4
    return values


# ---------------------------------------------------------------- heuristic

def test_two_consecutive_samples_switch_on_one_does_not():
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    assert feed(d, [s(tout=35, tin=33), s(), s()]) == [False, False, True]
    # Null control: a single defrost sample between normal ones never fires.
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    assert feed(d, [s(), s(tout=35, tin=33), s(), s(tout=35, tin=33)]) == [False] * 4


def test_threshold_is_inclusive_at_minus_one_kelvin():
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    assert feed(d, [s(tout=32.0, tin=33.0)] * 2)[-1] is True
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    assert feed(d, [s(tout=32.1, tin=33.0)] * 2)[-1] is False


def test_only_heating_modes_count():
    for mode in ("heat", "HEATDHW", "DHW"):
        d = defrost.DefrostDetector({**CFG, "confirm": []})
        assert feed(d, [s(mode=mode)] * 2)[-1] is True, mode
    # Null control: cooling makes supply < return by design.
    for mode in ("cool", "COOLDHW"):
        d = defrost.DefrostDetector({**CFG, "confirm": []})
        assert feed(d, [s(mode=mode)] * 2) == [False, False], mode


def test_confirm_rise_needed_when_confirm_data_exists():
    # T3 rises 2.5 K across the streak: confirmed.
    d = defrost.DefrostDetector(CFG)
    states = feed(d, [s(tout=35, tin=33, t3=-6.0), s(t3=-5.0), s(t3=-3.5)])
    assert states == [False, False, True] and d.confirmed is True
    # Null control: same water signal, coil flat -> not a defrost.
    d = defrost.DefrostDetector(CFG)
    states = feed(d, [s(tout=35, tin=33, t3=-6.0), s(t3=-6.0), s(t3=-5.5)])
    assert states == [False, False, False] and d.confirmed is False


def test_confirm_rise_threshold_and_either_input():
    d = defrost.DefrostDetector(CFG)
    assert feed(d, [s(t3=-6.0, t4=1.0), s(t3=-6.0, t4=3.0)])[-1] is True  # T4 +2.0
    d = defrost.DefrostDetector(CFG)
    assert feed(d, [s(t3=-6.0, t4=1.0), s(t3=-6.0, t4=2.9)])[-1] is False  # +1.9


def test_no_confirm_data_falls_back_to_water_signal():
    d = defrost.DefrostDetector(CFG)  # confirm codes named, no values
    assert feed(d, [s(), s()])[-1] is True and d.confirmed is None


def test_switches_off_on_first_normal_sample_and_stays_on_meanwhile():
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    assert feed(d, [s(), s(), s(), s(), s(tout=35, tin=33)]) == [False, True, True, True, False]


def test_close_updates_are_one_sample():
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    # Two updates 5 s apart (pushed DP burst): still one sample.
    assert d.update(s().get, now=0.0) is False
    assert d.update(s().get, now=5.0) is False
    # Null control: the same two updates a full poll apart do count.
    assert d.update(s().get, now=60.0) is True


def test_missing_inputs_are_unknown_and_reset_the_streak():
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    states = feed(d, [s(), {"mode": "heat", "Tout": 30.0}, s()])
    assert states == [False, None, False]


def test_thresholds_are_module_constants():
    assert defrost.DEFROST_DELTA_T_K == -1.0
    assert defrost.DEFROST_CONSECUTIVE_SAMPLES == 2
    assert defrost.DEFROST_CONFIRM_RISE_K == 2.0
    d = defrost.DefrostDetector({**CFG, "confirm": []})
    assert d.delta_t_k == defrost.DEFROST_DELTA_T_K
    assert d.samples_needed == defrost.DEFROST_CONSECUTIVE_SAMPLES


# ---------------------------------------------------------- coordinator

class _States:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, entity_id):
        value = self._m.get(entity_id)
        return None if value is None else types.SimpleNamespace(state=value)


def coord(data=None, detection=CFG, entity=None, states=None):
    c = C.__new__(C)
    c.model_mapping = {"sensors": windmi.SENSOR_TYPES, "defrost_detection": detection}
    c.data = data or {}
    c._sensor_offsets = {}
    c._defrost_detector = None
    c.defrost_entity_id = entity
    c.hass = types.SimpleNamespace(states=_States(states or {}))
    c._listeners = {}
    return c


def props(**values):
    return {k: {"value": v} for k, v in values.items()}


def test_coordinator_runs_heuristic_on_each_update():
    c = coord(props(mode="heat", Tout=30, Tin=33))
    c._update_defrost(now=0.0)
    assert c.defrost_active is False
    c._update_defrost(now=60.0)
    assert c.defrost_active is True and c.defrost_source == "heuristic"
    # Null control: a model without DEFROST_DETECTION has no state at all.
    bare = coord(props(mode="heat", Tout=30, Tin=33), detection=None)
    bare._update_defrost(now=0.0)
    bare._update_defrost(now=60.0)
    assert bare.defrost_active is None and bare.defrost_supported is False


def test_async_update_listeners_advances_heuristic():
    c = coord(props(mode="heat", Tout=30, Tin=33))
    c.async_update_listeners()
    assert c._defrost_detector is not None and c._defrost_detector.active is False


def test_option_entity_overrides_heuristic():
    data = props(mode="heat", Tout=30, Tin=33)
    c = coord(data, entity="binary_sensor.hp_defrost", states={"binary_sensor.hp_defrost": "off"})
    c._update_defrost(now=0.0)
    c._update_defrost(now=60.0)
    # Heuristic inputs say defrost; the entity says no -> no.
    assert c.defrost_active is False and c.defrost_source == "entity"
    c.hass.states = _States({"binary_sensor.hp_defrost": "on"})
    assert c.defrost_active is True
    c.hass.states = _States({"binary_sensor.hp_defrost": "unavailable"})
    assert c.defrost_active is None
    # Works for a model with no heuristic at all.
    c2 = coord(detection=None, entity="binary_sensor.x", states={"binary_sensor.x": "on"})
    assert c2.defrost_supported and c2.defrost_active is True


def test_converted_value_applies_conversion_and_offset():
    c = coord(props(POWER=45, Tout=30))
    assert c.converted_value("POWER") == 4.5
    c._sensor_offsets = {"Tout": 0.5}
    assert c.converted_value("Tout") == 30.5
    assert c.converted_value("missing") is None


# --------------------------------------------------- Windmi model wiring

def estimate(code, data, defrost_state):
    c = coord(props(**data))
    c._defrost_detector = types.SimpleNamespace(active=defrost_state, confirmed=None)
    c.device_name = "hp"
    c.device_info = None
    c.last_update_success = True
    c.device_schema = {}
    return sensor_mod.TuyaHeatpumpSensor(c, code, windmi.SENSOR_TYPES[code]).native_value


BASE = dict(POWER=40, T4=5, Tout=30, Tin=27, mode="heat")


def test_estimates_follow_defrost_state():
    normal = estimate("heating_output_estimate", BASE, False)
    assert normal == 11.2
    assert estimate("heating_output_estimate", BASE, True) == 0.0
    # COP = 5.99 + 0.141*5 - 0.07*30 - 0.0016*5*30 = 4.355;
    # 11.2 / 4.355 = 2.57 kW, and 1.15x that in defrost = 2.96 kW.
    assert estimate("power_estimate", BASE, False) == 2.57
    assert estimate("power_estimate", BASE, True) == 2.96


def test_forced_defrost_flag_does_not_move_estimates():
    # Null control for the bug: dp 102 set, no defrost state.
    flagged = {**BASE, "DEF": True}
    assert estimate("heating_output_estimate", flagged, False) == 11.2
    assert estimate("power_estimate", flagged, False) == estimate("power_estimate", BASE, False)


def test_unknown_defrost_counts_as_not_defrosting():
    assert estimate("heating_output_estimate", BASE, None) == 11.2


def test_windmi_model_drops_dp102_binary_sensor_and_declares_detection():
    assert all(cfg.get("dp_id") != 102 for cfg in windmi.BINARY_SENSOR_TYPES.values())
    assert windmi.SWITCH_TYPES["force_defrost"]["dp_id"] == 102
    det = windmi.DEFROST_DETECTION
    assert det["supply"] == "Tout" and det["return"] == "Tin"
    assert det["replaces"] == "DEF"
    for code in ("Tout", "Tin", "T3", "T4"):
        assert code in windmi.SENSOR_TYPES
    for code in ("heating_output_estimate", "power_estimate"):
        formula = windmi.SENSOR_TYPES[code]["formula"]
        assert "DEFROST" in formula
        assert "DEF " not in formula.replace("DEFROST", "") and "DEF)" not in formula


def test_model_loader_exposes_defrost_detection():
    loader = importlib.import_module(f"{PKG}.model_loader")
    loader.clear_model_cache("000004k4z6")
    mapping = loader.load_model_mapping("000004k4z6")
    assert mapping["defrost_detection"]["replaces"] == "DEF"


# ------------------------------------------------- binary sensor + migration

class _Registry:
    def __init__(self, entries):
        self.entries = dict(entries)  # unique_id -> entity_id
        self.updates = []

    def async_get_entity_id(self, domain, platform, unique_id):
        return self.entries.get(unique_id)

    def async_update_entity(self, entity_id, new_unique_id=None):
        self.updates.append((entity_id, new_unique_id))


def ent_coord(**kw):
    c = coord(**kw)
    c.device_name = "My HP"
    c.device_info = None
    c.last_update_success = True
    c.device_schema = {}
    c.model_mapping = {**c.model_mapping, "binary_sensors": windmi.BINARY_SENSOR_TYPES}
    return c


def setup_binary(c, monkeypatch, registry):
    monkeypatch.setattr(binary_mod.er, "async_get", lambda hass: registry)
    made = []
    hass = types.SimpleNamespace(data={const.DOMAIN: {"e1": c}})
    asyncio.run(binary_mod.async_setup_entry(hass, types.SimpleNamespace(entry_id="e1"), made.extend))
    return made


def test_old_defrosting_entity_is_migrated(monkeypatch):
    c = ent_coord(detection={**CFG, "replaces": "DEF"})
    reg = _Registry({"my_hp_DEF": "binary_sensor.my_hp_defrosting"})
    made = setup_binary(c, monkeypatch, reg)
    assert reg.updates == [("binary_sensor.my_hp_defrosting", "my_hp_defrost")]
    sensors = [e for e in made if isinstance(e, binary_mod.TuyaHeatpumpDefrostSensor)]
    assert len(sensors) == 1 and sensors[0].unique_id == "my_hp_defrost"
    assert sensors[0].name == "Defrost (suspected)"


def test_migration_null_controls(monkeypatch):
    # No old entity: nothing to move.
    c = ent_coord(detection={**CFG, "replaces": "DEF"})
    reg = _Registry({})
    setup_binary(c, monkeypatch, reg)
    assert reg.updates == []
    # New entity already registered: never overwrite it.
    reg = _Registry({"my_hp_DEF": "binary_sensor.a", "my_hp_defrost": "binary_sensor.b"})
    setup_binary(ent_coord(detection={**CFG, "replaces": "DEF"}), monkeypatch, reg)
    assert reg.updates == []
    # Old key still mapped by the model: it is not retired, leave it.
    c = ent_coord(detection={**CFG, "replaces": "fault"})
    reg = _Registry({"my_hp_fault": "binary_sensor.my_hp_fault_alarm"})
    setup_binary(c, monkeypatch, reg)
    assert reg.updates == []


def test_no_defrost_sensor_without_a_source(monkeypatch):
    c = ent_coord(detection=None)
    made = setup_binary(c, monkeypatch, _Registry({}))
    assert not [e for e in made if isinstance(e, binary_mod.TuyaHeatpumpDefrostSensor)]


def test_defrost_sensor_reports_entity_source():
    c = ent_coord(entity="binary_sensor.mb_defrost", states={"binary_sensor.mb_defrost": "on"})
    e = binary_mod.TuyaHeatpumpDefrostSensor(c)
    assert e.name == "Defrost" and e.is_on is True and e.available is True
    assert e.extra_state_attributes == {"source": "entity", "source_entity": "binary_sensor.mb_defrost"}
    c.hass.states = _States({})
    assert e.available is False


# ---------------------------------------------------------- options flow

def run_flow_step(options, user_input):
    entry = types.SimpleNamespace(options=options, data={}, entry_id="e1")
    flow = flow_mod.TuyaHeatpumpOptionsFlow(entry)
    flow.flow_id = "f"
    flow.handler = "e1"
    flow.hass = types.SimpleNamespace(data={})
    return asyncio.run(flow.async_step_defrost_options(user_input))


def test_options_step_sets_and_clears_entity_keeping_other_options():
    result = run_flow_step({"scan_interval": 5}, {const.CONF_DEFROST_ENTITY: "binary_sensor.mb"})
    assert result["data"] == {"scan_interval": 5, "defrost_entity": "binary_sensor.mb"}
    result = run_flow_step({"scan_interval": 5, "defrost_entity": "binary_sensor.mb"}, {})
    assert result["data"] == {"scan_interval": 5}


def test_options_step_shows_form():
    result = run_flow_step({}, None)
    assert result["step_id"] == "defrost_options"


def test_defrost_options_translated_everywhere():
    base = ROOT / "custom_components" / "tuya_heat_pump"
    for path in (base / "strings.json", *sorted((base / "translations").glob("*.json"))):
        steps = json.loads(path.read_text(encoding="utf-8"))["options"]["step"]
        assert "defrost_options" in steps["init"]["menu_options"], path
        assert "defrost_entity" in steps["defrost_options"]["data"], path
