"""Live register (data point) discovery for Tuya Heat Pump.

A static model file (``models/<modelId>.py``) is the curated, human-named
view of a device. It is written from one user's device dump and, by
nature, only covers the data points that person knew how to label.
Everything else the device reports -- extra probes, installer settings,
counters, raw blobs -- silently disappears.

This module closes that gap. It builds entity configs, in exactly the
same dict format the model files use, for every data point (DP) the
device actually exposes that the static model does not already cover.
Three sources feed it, richest first:

1. **Cloud "thing model" schema** (``/v2.0/cloud/thing/{id}/model``):
   dp_id, code, access mode (ro/rw/wr), type, min/max/step/scale/unit,
   enum ranges, bitmap labels and Tuya's own (usually Chinese) name.
   This is the same document the Tuya/Smart Life app renders its UI
   from, so it is the closest thing to an official register map.
2. **Cloud shadow properties** (``/shadow/properties``): code, dp_id,
   type and current value -- no ranges, but enough to type an entity.
3. **Local LAN status** (tinytuya ``status()``): dp_id and a Python value
   only. These show up as ``dp_<id>`` codes.

The output is merged into the coordinator's ``model_mapping`` after the
first refresh, so the normal sensor/switch/number/select platforms pick
the discovered entries up without any special casing. Every generated
config carries ``"discovered": True`` so other parts of the integration
(e.g. the MQTT coverage check) can tell them apart from curated ones.

This file deliberately has **no Home Assistant imports**: it is also used
by ``test/discovery_preview.py`` to show, offline, what a device dump
would turn into.
"""
from __future__ import annotations

import re
from typing import Any

ENTITY_CATEGORIES = ("sensors", "binary_sensors", "switches", "numbers", "selects", "texts")

# ---------------------------------------------------------------------------
# Tuya "thing model" parsing
# ---------------------------------------------------------------------------


def parse_device_schema(model_info: dict | None) -> dict[int, dict]:
    """Turn the decoded ``model`` JSON of the thing-model API into a flat
    ``{dp_id: property}`` dict.

    Each property is normalised to::

        {
            "dp_id": 104, "code": "DHWSET", "name": "生活热水设定",
            "access": "rw", "type": "value",
            "spec": {"min": 40, "max": 60, "step": 1, "scale": 0, "unit": "℃"},
        }

    Unknown/malformed entries are skipped rather than raising -- a partial
    schema is still far more useful than none.
    """
    schema: dict[int, dict] = {}
    if not isinstance(model_info, dict):
        return schema
    for service in model_info.get("services", []) or []:
        for prop in service.get("properties", []) or []:
            try:
                dp_id = int(prop["abilityId"])
                code = str(prop["code"])
            except (KeyError, TypeError, ValueError):
                continue
            type_spec = prop.get("typeSpec") or {}
            spec = {k: v for k, v in type_spec.items() if k != "type"}
            schema[dp_id] = {
                "dp_id": dp_id,
                "code": code,
                "name": prop.get("name") or "",
                "access": (prop.get("accessMode") or "ro").lower(),
                "type": (type_spec.get("type") or "").lower(),
                "spec": spec,
            }
    return schema


def compact_schema(schema: dict[int, dict]) -> list[dict]:
    """JSON-friendly form of :func:`parse_device_schema` output, used to
    cache the schema in the config entry so a restart does not need the
    cloud just to know what the device looks like."""
    return [schema[dp_id] for dp_id in sorted(schema)]


def schema_from_cache(cached: Any) -> dict[int, dict]:
    """Inverse of :func:`compact_schema`. Tolerates garbage."""
    schema: dict[int, dict] = {}
    if not isinstance(cached, list):
        return schema
    for entry in cached:
        try:
            dp_id = int(entry["dp_id"])
            schema[dp_id] = {
                "dp_id": dp_id,
                "code": str(entry["code"]),
                "name": entry.get("name") or "",
                "access": entry.get("access") or "ro",
                "type": entry.get("type") or "",
                "spec": entry.get("spec") or {},
            }
        except (KeyError, TypeError, ValueError):
            continue
    return schema


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

# Tuya names DPs in Chinese in the thing model. Midea-derived heat pump
# firmware (Rotenso, Fisher, Kaisai, Sinclair, ...) uses a fairly small
# vocabulary, so a longest-match substring glossary gets most names into
# readable English. Anything left untranslated is dropped and the code is
# used instead; the original name is still exposed as an attribute.
_CJK_GLOSSARY: dict[str, str] = {
    # Full phrases seen on Midea/Tuya heat pumps
    "总出水温度": "Total Outlet Water Temperature",
    "换热器进水温度": "Heat Exchanger Inlet Water Temperature",
    "换热器出水温度": "Heat Exchanger Outlet Water Temperature",
    "室外环境温度": "Outdoor Ambient Temperature",
    "线控器温度": "Wired Controller Temperature",
    "水箱电加热": "Tank Electric Heater",
    "生活热水设定": "DHW Setpoint",
    "生活热水": "DHW",
    "杀菌模式": "Disinfection Mode",
    "强制除霜": "Forced Defrost",
    "故障告警": "Fault Alarm",
    "温度设置": "Temperature Setpoint",
    "温度设定": "Temperature Setpoint",
    "即时加热": "Instant Heating",
    "水箱温度": "Tank Temperature",
    "水泵档位": "Water Pump Level",
    "能需": "Energy Demand",
    # Compound terms
    "进水温度": "Inlet Water Temperature",
    "出水温度": "Outlet Water Temperature",
    "回水温度": "Return Water Temperature",
    "排气温度": "Discharge Temperature",
    "吸气温度": "Suction Temperature",
    "盘管温度": "Coil Temperature",
    "环境温度": "Ambient Temperature",
    "室内温度": "Indoor Temperature",
    "室外温度": "Outdoor Temperature",
    "电加热": "Electric Heater",
    "膨胀阀": "Expansion Valve",
    "四通阀": "4-Way Valve",
    "三通阀": "3-Way Valve",
    "缓冲罐": "Buffer Tank",
    "太阳能": "Solar",
    "室外机": "Outdoor Unit",
    "室内机": "Indoor Unit",
    "压缩机": "Compressor",
    "冷媒": "Refrigerant",
    "液管": "Liquid Pipe",
    "气管": "Gas Pipe",
    "高压": "High Pressure",
    "低压": "Low Pressure",
    "上限": "Upper Limit",
    "下限": "Lower Limit",
    "水流": "Water Flow",
    "地暖": "Floor Heating",
    "热水": "Hot Water",
    "一区": "Zone 1",
    "二区": "Zone 2",
    "区域": "Zone",
    "房间": "Room",
    "锅炉": "Boiler",
    "水泵": "Water Pump",
    "水箱": "Tank",
    "风机": "Fan",
    "风扇": "Fan",
    "开关": "Power",
    "模式": "Mode",
    "定时": "Timer",
    "计时": "Timer",
    # Single terms
    "温度": "Temperature",
    "设定": "Setpoint",
    "设置": "Setting",
    "电流": "Current",
    "电压": "Voltage",
    "功率": "Power",
    "频率": "Frequency",
    "电量": "Energy",
    "流量": "Flow",
    "压力": "Pressure",
    "转速": "Speed",
    "档位": "Level",
    "开度": "Opening",
    "故障": "Fault",
    "告警": "Alarm",
    "除霜": "Defrost",
    "制热": "Heating",
    "制冷": "Cooling",
    "供暖": "Heating",
    "加热": "Heating",
    "静音": "Silent",
    "夜间": "Night",
    "节能": "ECO",
    "假期": "Holiday",
    "曲线": "Curve",
    "消毒": "Disinfection",
    "运行": "Running",
    "状态": "Status",
    "累计": "Total",
    "时间": "Time",
    "版本": "Version",
    "软件": "Software",
    "型号": "Model",
    "机组": "Unit",
    "模块": "Module",
    "补水": "Water Refill",
    "第一": "First",
    "第二": "Second",
    "阀": "Valve",
    "总": "Total",
    "水": "Water",
    "电": "Electric",
}
_CJK_KEYS_LONGEST_FIRST = sorted(_CJK_GLOSSARY, key=len, reverse=True)
_CJK_RE = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")

# Word-level replacements when a name has to be derived from the code.
_CODE_WORDS: dict[str, str] = {
    "temp": "Temperature",
    "tmp": "Temperature",
    "cur": "Current",
    "curr": "Current",
    "vol": "Voltage",
    "volt": "Voltage",
    "freq": "Frequency",
    "comp": "Compressor",
    "dhw": "DHW",
    "set": "Setpoint",
    "amb": "Ambient",
    "def": "Defrost",
    "wp": "Water Pump",
    "pwr": "Power",
    "hz": "Hz",
    "kwh": "kWh",
    "ac": "AC",
    "dc": "DC",
    "eev": "EEV",
    "ipm": "IPM",
    "cop": "COP",
    "pv": "PV",
    "sg": "SG",
    "id": "ID",
}


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def translate_cn_name(name: str) -> str:
    """Best-effort Chinese -> English via the glossary. Returns '' when
    nothing translatable remains so callers can fall back to the code."""
    if not name:
        return ""
    out = name
    for key in _CJK_KEYS_LONGEST_FIRST:
        if key in out:
            out = out.replace(key, f" {_CJK_GLOSSARY[key]} ")
    # Drop any leftover CJK and tidy whitespace.
    out = _CJK_RE.sub(" ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def name_from_code(code: str) -> str:
    """``in_water_temp`` -> ``In Water Temperature``; ``DHWSET`` stays
    ``DHWSET``; ``dp_112`` -> ``DP 112``."""
    if not code:
        return "Unknown"
    if re.fullmatch(r"dp_\d+", code):
        return "DP " + code[3:]
    parts = [p for p in re.split(r"[_\-\s]+", code) if p]
    words = []
    for part in parts:
        low = part.lower()
        if low in _CODE_WORDS:
            words.append(_CODE_WORDS[low])
        elif part.isupper() or (any(c.isupper() for c in part[1:])):
            # Already an abbreviation / mixed-case token (Tin, DHWSET, T1B)
            words.append(part)
        else:
            words.append(part.capitalize())
    return " ".join(words)


def friendly_name(code: str, cn_name: str = "") -> str:
    """Pick the best human name for a DP."""
    if cn_name and not _has_cjk(cn_name):
        return cn_name.strip() or name_from_code(code)
    translated = translate_cn_name(cn_name)
    if translated and len(translated) >= 3:
        return translated
    return name_from_code(code)


# ---------------------------------------------------------------------------
# Unit / device-class heuristics
# ---------------------------------------------------------------------------

# Tuya unit string -> (HA unit, device_class, state_class)
_UNIT_MAP: dict[str, tuple[str, str | None, str | None]] = {
    "℃": ("°C", "temperature", "measurement"),
    "°c": ("°C", "temperature", "measurement"),
    "°C": ("°C", "temperature", "measurement"),
    "c": ("°C", "temperature", "measurement"),
    "℉": ("°F", "temperature", "measurement"),
    "°f": ("°F", "temperature", "measurement"),
    "°F": ("°F", "temperature", "measurement"),
    "f": ("°F", "temperature", "measurement"),
    "w": ("W", "power", "measurement"),
    "kw": ("kW", "power", "measurement"),
    "kwh": ("kWh", "energy", "total_increasing"),
    "kw·h": ("kWh", "energy", "total_increasing"),
    "kw.h": ("kWh", "energy", "total_increasing"),
    "wh": ("Wh", "energy", "total_increasing"),
    "a": ("A", "current", "measurement"),
    "ma": ("mA", "current", "measurement"),
    "v": ("V", "voltage", "measurement"),
    "mv": ("mV", "voltage", "measurement"),
    "hz": ("Hz", "frequency", "measurement"),
    "%": ("%", None, "measurement"),
    "kpa": ("kPa", "pressure", "measurement"),
    "mpa": ("MPa", "pressure", "measurement"),
    "bar": ("bar", "pressure", "measurement"),
    "pa": ("Pa", "pressure", "measurement"),
    "psi": ("psi", "pressure", "measurement"),
    "l/min": ("L/min", None, "measurement"),
    "l/m": ("L/min", None, "measurement"),
    "lpm": ("L/min", None, "measurement"),
    "m³/h": ("m³/h", None, "measurement"),
    "m3/h": ("m³/h", None, "measurement"),
    "h": ("h", "duration", "measurement"),
    "hour": ("h", "duration", "measurement"),
    "min": ("min", "duration", "measurement"),
    "s": ("s", "duration", "measurement"),
    "rpm": ("rpm", None, "measurement"),
    "r/min": ("rpm", None, "measurement"),
    "l": ("L", None, "measurement"),
    "ppm": ("ppm", None, "measurement"),
}

_ICON_BY_DEVICE_CLASS = {
    "temperature": "mdi:thermometer",
    "power": "mdi:flash",
    "energy": "mdi:lightning-bolt",
    "current": "mdi:current-ac",
    "voltage": "mdi:sine-wave",
    "frequency": "mdi:sine-wave",
    "pressure": "mdi:gauge",
    "duration": "mdi:timer-outline",
}


def _unit_info(unit: str | None) -> tuple[str | None, str | None, str | None]:
    if not unit:
        return None, None, "measurement"
    key = str(unit).strip()
    return _UNIT_MAP.get(key) or _UNIT_MAP.get(key.lower()) or (key, None, "measurement")


def _guess_icon(code: str, name: str, device_class: str | None) -> str | None:
    if device_class in _ICON_BY_DEVICE_CLASS:
        return _ICON_BY_DEVICE_CLASS[device_class]
    text = f"{code} {name}".lower()
    if "pump" in text:
        return "mdi:water-pump"
    if "fan" in text:
        return "mdi:fan"
    if "defrost" in text or "def" == code.lower():
        return "mdi:snowflake-melt"
    if "fault" in text or "error" in text or "alarm" in text:
        return "mdi:alert-circle"
    if "timer" in text:
        return "mdi:timer-outline"
    if "mode" in text:
        return "mdi:tune"
    if "night" in text or "silent" in text or "quiet" in text:
        return "mdi:weather-night"
    if "heat" in text:
        return "mdi:heating-coil"
    return None


# ---------------------------------------------------------------------------
# Coverage: what the static model already provides
# ---------------------------------------------------------------------------


def static_coverage(static_mapping: dict) -> tuple[set[int], set[str]]:
    """Return (dp_ids, codes) that the static model file already handles.
    Raw-field entries cover their whole raw DP."""
    dp_ids: set[int] = set()
    codes: set[str] = set()
    for category in ENTITY_CATEGORIES:
        for key, cfg in (static_mapping.get(category) or {}).items():
            if not isinstance(cfg, dict):
                continue
            dp_id = cfg.get("dp_id")
            if dp_id is not None:
                try:
                    dp_ids.add(int(dp_id))
                except (TypeError, ValueError):
                    pass
            raw_source = cfg.get("raw_source")
            if raw_source:
                codes.add(raw_source)
            codes.add(cfg.get("code", key))
    return dp_ids, codes


# ---------------------------------------------------------------------------
# Entity config generation
# ---------------------------------------------------------------------------


def _bitmap_conversion(labels: list[str]) -> str:
    pairs = ", ".join(f"({1 << i}, {label!r})" for i, label in enumerate(labels))
    return f"', '.join(n for b, n in [{pairs}] if value & b) or 'OK'"


def _base(prop: dict, extra: dict | None = None) -> dict:
    """Common keys every discovered config carries."""
    cfg = {
        "dp_id": prop["dp_id"],
        "code": prop["code"],
        "discovered": True,
        "tuya_type": prop.get("type") or "",
        "tuya_access": prop.get("access") or "",
    }
    if prop.get("name"):
        cfg["tuya_name"] = prop["name"]
    if extra:
        cfg.update(extra)
    return cfg


def configs_for_property(prop: dict) -> dict[str, list[tuple[str, dict]]]:
    """Generate entity configs for one schema property.

    Returns ``{category: [(key, config), ...]}``. A single DP can yield
    more than one entity (a bitmap yields a description sensor plus a
    problem binary sensor).
    """
    out: dict[str, list[tuple[str, dict]]] = {c: [] for c in ENTITY_CATEGORIES}
    code = prop["code"]
    dp_type = prop.get("type") or ""
    access = prop.get("access") or "ro"
    spec = prop.get("spec") or {}
    name = friendly_name(code, prop.get("name") or "")
    writable = access in ("rw", "wr")

    if dp_type == "value":
        scale = int(spec.get("scale") or 0)
        factor = 10 ** scale
        unit, device_class, state_class = _unit_info(spec.get("unit"))
        conversion = f"value / {factor}" if scale > 0 else "value"
        icon = _guess_icon(code, name, device_class)
        if writable:
            step = spec.get("step") or 1
            cfg = _base(prop, {
                "name": name,
                "unit": unit,
                "icon": icon or "mdi:tune-variant",
                "min_value": float(spec.get("min", 0)) / factor,
                "max_value": float(spec.get("max", 100)) / factor,
                "step": max(float(step) / factor, 1 / factor),
                "conversion": conversion,
                "api_conversion": f"int(round(value * {factor}))" if scale > 0 else "int(round(value))",
                "entity_category": "config",
            })
            out["numbers"].append((code, cfg))
        else:
            cfg = _base(prop, {
                "name": name,
                "unit": unit,
                "icon": icon,
                "device_class": device_class,
                "state_class": state_class,
                "conversion": conversion,
            })
            out["sensors"].append((code, cfg))

    elif dp_type == "bool":
        icon = _guess_icon(code, name, None)
        if writable:
            cfg = _base(prop, {
                "name": name,
                "icon": icon or "mdi:toggle-switch",
                "conversion": "value in [1, True, '1', 'true', 'on', 'yes', 'enable', 'open']",
                "entity_category": "config",
            })
            out["switches"].append((code, cfg))
        else:
            text = f"{code} {name}".lower()
            device_class = None
            if "fault" in text or "error" in text or "alarm" in text:
                device_class = "problem"
            elif "defrost" in text:
                device_class = "cold"
            elif "run" in text or "on" == code.lower():
                device_class = "running"
            cfg = _base(prop, {
                "name": name,
                "device_class": device_class,
                "conversion": "value in [1, True, '1', 'true', 'on', 'yes', 'enable', 'open']",
            })
            out["binary_sensors"].append((code, cfg))

    elif dp_type == "enum":
        options = [str(o) for o in (spec.get("range") or [])]
        labels = {o: name_from_code(o) for o in options}
        if writable and options:
            cfg = _base(prop, {
                "name": name,
                "icon": _guess_icon(code, name, None) or "mdi:format-list-bulleted",
                "options": labels,
                "entity_category": "config",
            })
            out["selects"].append((code, cfg))
        else:
            cfg = _base(prop, {
                "name": name,
                "icon": _guess_icon(code, name, None) or "mdi:format-list-bulleted",
                "value_map": labels or None,
            })
            out["sensors"].append((code, cfg))

    elif dp_type == "bitmap":
        labels = [str(label) for label in (spec.get("label") or [])]
        if not labels:
            maxlen = int(spec.get("maxlen") or 16)
            labels = [f"bit{i}" for i in range(maxlen)]
        cfg = _base(prop, {
            "name": f"{name} Description" if not name.lower().endswith("description") else name,
            "icon": "mdi:alert-circle",
            "conversion": _bitmap_conversion(labels),
        })
        out["sensors"].append((f"{code}_description", cfg))
        text = f"{code} {name}".lower()
        if "fault" in text or "error" in text or "alarm" in text or labels[0][:1] in ("E", "P", "F"):
            bcfg = _base(prop, {
                "name": name,
                "device_class": "problem",
                "conversion": "value != 0",
            })
            out["binary_sensors"].append((code, bcfg))

    elif dp_type == "string":
        cfg = _base(prop, {
            "name": name,
            "icon": "mdi:text",
            "entity_category": "diagnostic",
        })
        out["sensors"].append((code, cfg))

    elif dp_type == "raw":
        # Opaque blob; surface it (base64, as received) as a disabled
        # diagnostic so people can watch it change in raw_explorer.py
        # style without cluttering the device page.
        cfg = _base(prop, {
            "name": f"{name} (raw)",
            "icon": "mdi:code-brackets",
            "entity_category": "diagnostic",
            "enabled_default": False,
        })
        out["sensors"].append((code, cfg))

    else:
        # Unknown type: expose as a plain sensor so the value is at least visible.
        cfg = _base(prop, {"name": name, "entity_category": "diagnostic"})
        out["sensors"].append((code, cfg))

    return out


# ---------------------------------------------------------------------------
# Fallback typing when there is no schema
# ---------------------------------------------------------------------------

_TUYA_TYPES = {"value", "bool", "enum", "bitmap", "raw", "string"}


def property_from_live(code: str, entry: dict, dp_id: int | None) -> dict | None:
    """Build a pseudo schema property from a live coordinator.data entry.

    Cloud entries carry Tuya's type string; local ones carry a Python
    type name. Access mode is unknown, so everything is treated as
    read-only -- safe by construction.
    """
    value = entry.get("value")
    tuya_type = str(entry.get("type") or "").lower()
    if tuya_type not in _TUYA_TYPES:
        if isinstance(value, bool):
            tuya_type = "bool"
        elif isinstance(value, (int, float)):
            tuya_type = "value"
        elif isinstance(value, str):
            # Heuristic: base64-looking, longer strings are raw blobs.
            if len(value) >= 8 and re.fullmatch(r"[A-Za-z0-9+/=]+", value):
                tuya_type = "raw"
            else:
                tuya_type = "string"
        else:
            return None
    if dp_id is None:
        match = re.fullmatch(r"dp_(\d+)", code)
        if match:
            dp_id = int(match.group(1))
    return {
        "dp_id": dp_id,
        "code": code,
        "name": "",
        "access": "ro",
        "type": tuya_type,
        "spec": {},
    }


# ---------------------------------------------------------------------------
# Top-level: build the mapping delta
# ---------------------------------------------------------------------------


def build_discovered_mapping(
    schema: dict[int, dict] | None,
    live_data: dict | None,
    static_mapping: dict,
) -> dict[str, dict]:
    """Return ``{category: {key: config}}`` for every DP not covered by
    ``static_mapping``.

    A schema property is only turned into an entity when the device has
    actually reported a value for it (present in ``live_data``) or when it
    is write-only -- a DP that never reports would otherwise sit there as
    a permanently unavailable entity.
    """
    schema = schema or {}
    live_data = live_data or {}
    static_dp_ids, static_codes = static_coverage(static_mapping)

    result: dict[str, dict] = {c: {} for c in ENTITY_CATEGORIES}
    used_keys: dict[str, set[str]] = {c: set(static_mapping.get(c) or {}) for c in ENTITY_CATEGORIES}
    handled_codes: set[str] = set()

    def _add(category: str, key: str, cfg: dict) -> None:
        # Never shadow a curated entity with the same key.
        if key in used_keys[category]:
            key = f"{key}_dp{cfg['dp_id']}"
            if key in used_keys[category]:
                return
        used_keys[category].add(key)
        result[category][key] = cfg

    # 1) Schema-driven (rich)
    for dp_id in sorted(schema):
        prop = schema[dp_id]
        code = prop["code"]
        if dp_id in static_dp_ids or code in static_codes:
            handled_codes.add(code)
            continue
        reported = code in live_data or f"dp_{dp_id}" in live_data
        if not reported and prop.get("access") != "wr":
            continue
        if code not in live_data and f"dp_{dp_id}" in live_data:
            # Local mode before the schema-based dp_mapping kicked in.
            prop = {**prop, "code": f"dp_{dp_id}"}
            code = prop["code"]
        handled_codes.add(code)
        for category, items in configs_for_property(prop).items():
            for key, cfg in items:
                _add(category, key, cfg)

    # 2) Live-data driven (type only) for anything the schema does not list
    schema_codes = {p["code"] for p in schema.values()}
    for code, entry in live_data.items():
        if code in static_codes or code in handled_codes or code in schema_codes:
            continue
        if not isinstance(entry, dict):
            continue
        prop = property_from_live(code, entry, entry.get("dp_id"))
        if prop is None:
            continue
        dp_id = prop.get("dp_id")
        if dp_id is not None and dp_id in static_dp_ids:
            continue
        handled_codes.add(code)
        for category, items in configs_for_property(prop).items():
            for key, cfg in items:
                _add(category, key, cfg)

    return result


def count_entities(mapping: dict[str, dict]) -> int:
    return sum(len(mapping.get(c) or {}) for c in ENTITY_CATEGORIES)


def unmapped_codes(live_data: dict | None, full_mapping: dict) -> list[str]:
    """Codes present in live data that no entity (static or discovered)
    reads. Useful in diagnostics to see what is still hidden."""
    live_data = live_data or {}
    _, codes = static_coverage(full_mapping)
    return sorted(code for code in live_data if code not in codes)
