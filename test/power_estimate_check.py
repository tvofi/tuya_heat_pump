"""Estimated Power Draw stays numeric while the Rotenso Windmi is heating.

beta08's power_estimate formula returned None — Home Assistant state
"unknown" — whenever plate-HX outlet water (Tout, dp 106) was <= 25 C
and the unit was not defrosting. That comparison was a stand-in for
"this is cooling, and the COP fit has no EER terms". On a heating
system Tout crosses 25 C every cycle (idle, ramp-up, low-temperature
circuit; the heating setpoint floor is 25 C and the test is strict),
so the entity was unknown about 60% of the time. Estimated Heating
Output only needs POWER, so it kept showing a value.

The gate is the operation mode (dp 2): heat / DHW / HEATDHW always
estimate; cool stays unknown unless defrosting; COOLDHW and a mode
missing from the poll keep the Tout > 25 fallback.

Usage:
    python3 test/power_estimate_check.py [path/to/custom_components/tuya_heat_pump]
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp_liveness_check as live  # noqa: E402


def _load_model(integration_dir: Path):
    spec = importlib.util.spec_from_file_location(
        "windmi_000004k4z6", integration_dir / "models" / "000004k4z6.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reading(sensor_mod, coord_cls, model, data, code):
    coordinator = live.make_coord(coord_cls, data=data)
    coordinator.model_mapping = {
        "sensors": model.SENSOR_TYPES,
        "binary_sensors": model.BINARY_SENSOR_TYPES,
        "selects": model.SELECT_TYPES,
    }
    coordinator._sensor_offsets = {}
    entity = sensor_mod.TuyaHeatpumpSensor(
        coordinator, code, model.SENSOR_TYPES[code]
    )
    return entity.available, entity.native_value


def _props(**values):
    return {key: {"value": value} for key, value in values.items()}


# WIM140 at 5.0 HP, outdoor 7 C. COP at Tout 22 C is 5.1906,
# so 14 kW / 5.1906 = 2.70 kW; defrost holds 1.15x = 3.10 kW.
# At Tout 30 C COP is 4.541 → 3.08 kW. At Tout 40 C COP is 3.729 → 3.75 kW.
_BASE = dict(POWER=50, T4=7, Tout=22, DEF=0, mode="heat")


def check_all(sensor_mod, coord_cls, model):
    results = []

    def record(name, condition, detail=""):
        results.append((name, bool(condition), detail))

    def power(data):
        return _reading(sensor_mod, coord_cls, model, data, "power_estimate")

    def heat(data):
        return _reading(
            sensor_mod, coord_cls, model, data, "heating_output_estimate"
        )

    # The reported bug: heating, leaving water at or below 25 C.
    available, value = power(_props(**_BASE))
    record(
        "heat + Tout 22 C → numeric, not unknown",
        available is True and value == 2.70,
        f"available={available} value={value}",
    )
    available, value = power(_props(**{**_BASE, "Tout": 25}))
    record(
        "heat + Tout exactly 25 C → numeric",
        available is True and isinstance(value, float),
        f"available={available} value={value}",
    )
    available, heating = heat(_props(**_BASE))
    record(
        "heating output still numeric on the same sample",
        available is True and heating == 14.0,
        f"available={available} value={heating}",
    )

    # Defrost while heating and cold: max-level input, output dropped to 0.
    available, value = power(_props(**{**_BASE, "DEF": True}))
    record(
        "heat + defrost → 1.15x draw",
        available is True and value == 3.10,
        f"value={value}",
    )
    _, heating = heat(_props(**{**_BASE, "DEF": True}))
    record("heating output drops to 0 during defrost", heating == 0.0, str(heating))

    # DHW and combined heating follow the same COP model.
    for mode in ("DHW", "HEATDHW"):
        available, value = power(_props(**{**_BASE, "mode": mode}))
        record(
            f"{mode} + cold outlet → numeric",
            available is True and value == 2.70,
            f"value={value}",
        )

    # Cooling has no EER terms: stay unknown, unless defrosting.
    available, value = power(_props(**{**_BASE, "mode": "cool", "Tout": 12}))
    record(
        "cool → unknown (available)",
        available is True and value is None,
        f"available={available} value={value}",
    )
    # Tout 12 C → COP 6.0026, 14 kW / 6.0026 × 1.15 = 2.68 kW.
    available, value = power(_props(**{**_BASE, "mode": "cool", "Tout": 12, "DEF": 1}))
    record(
        "cool + defrost → numeric",
        available is True and value == 2.68,
        f"value={value}",
    )

    # COOLDHW may be chilling or making hot water; outlet temperature
    # is the only live hint, same 25 C line as before.
    available, value = power(_props(**{**_BASE, "mode": "COOLDHW", "Tout": 40}))
    record("COOLDHW + hot outlet → numeric", value == 3.75, f"value={value}")
    available, value = power(_props(**{**_BASE, "mode": "COOLDHW", "Tout": 12}))
    record("COOLDHW + cold outlet → unknown", value is None, f"value={value}")

    # Mode is report-on-change and can leave the cloud shadow. Fall back
    # to the old outlet test instead of going unknown for the season.
    stale = _props(**_BASE)
    del stale["mode"]
    available, value = power({**stale, "Tout": {"value": 30}})
    record("mode missing + Tout 30 C → numeric", value == 3.08, f"value={value}")
    available, value = power({**stale, "Tout": {"value": 20}})
    record("mode missing + Tout 20 C → unknown", value is None, f"value={value}")
    # Tout 20 C → COP 5.353, 14 kW / 5.353 × 1.15 = 3.01 kW.
    available, value = power({**stale, "Tout": {"value": 20}, "DEF": {"value": True}})
    record("mode missing + defrost → numeric", value == 3.01, f"value={value}")

    # A required temperature still blanks the estimate. Heating output
    # does not read T4, so it stays up — that split is not this bug.
    no_t4 = _props(**_BASE)
    del no_t4["T4"]
    _, value = power(no_t4)
    _, heating = heat(no_t4)
    record("T4 missing → power unknown", value is None, f"value={value}")
    record("T4 missing → heating output still numeric", heating == 14.0, str(heating))

    # DEF out of season: default 0, same as "not defrosting".
    no_def = _props(**_BASE)
    del no_def["DEF"]
    _, value = power(no_def)
    record("DEF missing defaults to not defrosting", value == 2.70, f"value={value}")

    # Unrelated formula still subtracts two temperatures.
    delta = sensor_mod.TuyaHeatpumpSensor(
        live.make_coord(
            coord_cls,
            data={"Tout": {"value": 35}, "Tin": {"value": 30}},
        ),
        "water_delta_t",
        model.SENSOR_TYPES["water_delta_t"],
    )
    delta.coordinator.model_mapping = {"sensors": model.SENSOR_TYPES}
    delta.coordinator._sensor_offsets = {}
    record("water ΔT formula unchanged", delta.native_value == 5.0, str(delta.native_value))

    # Without formula_inputs the scanner must not treat quoted enum keys
    # ('heat') or the keywords `is` / `in` as required sensor codes.
    quoted = sensor_mod.TuyaHeatpumpSensor(
        live.make_coord(coord_cls, data={"mode": {"value": "heat"}}),
        "quoted",
        {
            "name": "quoted",
            "formula": "1 if mode == 'heat' else 0",
            "formula_defaults": {"mode": None},
            "precision": 0,
        },
    )
    quoted.coordinator.model_mapping = {"sensors": {}}
    quoted.coordinator._sensor_offsets = {}
    record(
        "quoted enum key is not a required input",
        quoted.native_value == 1,
        str(quoted.native_value),
    )

    return results


def main() -> int:
    default_dir = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "tuya_heat_pump"
    )
    integration_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir
    if not (integration_dir / "sensor.py").exists():
        print(f"integration directory not found: {integration_dir}")
        return 2

    live._install_stubs()
    mods = live._load_integration(integration_dir)
    model = _load_model(integration_dir)
    results = check_all(
        mods["sensor"],
        mods["coordinator"].TuyaScaleDataUpdateCoordinator,
        model,
    )

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
