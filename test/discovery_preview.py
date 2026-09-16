"""
Register discovery preview / model file generator
=================================================
Shows, offline, which extra Home Assistant entities the integration's
live register discovery (custom_components/tuya_heat_pump/discovery.py)
would create for a device -- and can turn them into a ready-to-edit
model file -- without touching Home Assistant.

Input (first argument), any of:

  * the ``tuya_device_data_<timestamp>.txt`` file written by
    ``tuya_api_test.py`` (live properties + full device schema), or
  * the JSON file from Home Assistant's *Download diagnostics* on the
    heat pump device (contains the same schema and live values), or
  * a plain JSON dump of the thing-model API response.

Usage:

    python discovery_preview.py <dump-or-diagnostics.json>
    python discovery_preview.py <dump> ../custom_components/tuya_heat_pump/models/000004k4z6.py
    python discovery_preview.py <dump> [model.py] --emit-model > my_model.py

With a model file as second argument only what that model does NOT
already cover is shown. ``--emit-model`` prints the discovered entities
as a model file skeleton (SENSOR_TYPES, SWITCH_TYPES, ...) that you can
rename, fix up and drop into ``custom_components/tuya_heat_pump/models/``
or merge into the existing file for your modelId.

Requirements: none beyond the standard library.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "custom_components", "tuya_heat_pump"))

import discovery  # noqa: E402  (imported from the integration folder)


def _extract_json_blocks(text: str) -> list[dict]:
    """Pull every top-level JSON object out of a text dump."""
    blocks = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    blocks.append(json.loads(text[start:i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    return blocks


def load_dump(path: str) -> tuple[dict[int, dict], dict, str]:
    """Return (schema_by_dp_id, live_data, model_id) from any supported input."""
    text = open(path, encoding="utf-8").read()
    schema: dict[int, dict] = {}
    live: dict = {}
    model_id = "?"

    # 1) Home Assistant diagnostics JSON
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        doc = None
    if isinstance(doc, dict) and "data" in doc and isinstance(doc["data"], dict):
        doc = doc["data"]  # HA wraps diagnostics in {"home_assistant":…, "data":…}
    if isinstance(doc, dict) and "schema" in doc and "live_data" in doc:
        schema = discovery.schema_from_cache(doc.get("schema"))
        live = doc.get("live_data") or {}
        model_id = (doc.get("device") or {}).get("model_id", "?")
        return schema, live, model_id

    # 2) tuya_api_test.py dump / raw API responses
    for block in _extract_json_blocks(text):
        result = block.get("result", block) if isinstance(block, dict) else None
        if not isinstance(result, dict):
            continue
        if "properties" in result and isinstance(result["properties"], list):
            for prop in result["properties"]:
                code = prop.get("code")
                if code:
                    live[code] = {
                        "value": prop.get("value"),
                        "type": prop.get("type", ""),
                        "dp_id": prop.get("dp_id"),
                    }
        model_info = None
        if "model" in result:
            model_str = result["model"]
            try:
                model_info = json.loads(model_str) if isinstance(model_str, str) else model_str
            except json.JSONDecodeError:
                model_info = None
        elif "services" in result:
            model_info = result
        if model_info:
            schema = discovery.parse_device_schema(model_info)
            model_id = model_info.get("modelId", model_id)
    return schema, live, model_id


def load_model_file(path: str | None) -> dict:
    if not path:
        return {c: {} for c in discovery.ENTITY_CATEGORIES}
    spec = importlib.util.spec_from_file_location("model_file", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return {
        "sensors": getattr(module, "SENSOR_TYPES", {}),
        "binary_sensors": getattr(module, "BINARY_SENSOR_TYPES", {}),
        "switches": getattr(module, "SWITCH_TYPES", {}),
        "numbers": getattr(module, "NUMBER_TYPES", {}),
        "selects": getattr(module, "SELECT_TYPES", {}),
        "texts": getattr(module, "TEXT_TYPES", {}),
    }


_MODEL_VARS = {
    "sensors": "SENSOR_TYPES",
    "binary_sensors": "BINARY_SENSOR_TYPES",
    "switches": "SWITCH_TYPES",
    "numbers": "NUMBER_TYPES",
    "selects": "SELECT_TYPES",
    "texts": "TEXT_TYPES",
}
_DROP_KEYS = {"discovered", "tuya_type", "tuya_access"}


def emit_model(discovered: dict, model_id: str, live: dict) -> str:
    """Render discovered entities as a model file skeleton."""
    lines = [
        f'"""Model mapping skeleton generated by discovery_preview.py (modelId: {model_id})."""',
        "",
        f'MODEL_NAME = "Heat Pump ({model_id})"',
        "# ====================================================",
        "# Generated from the device's own Tuya schema. Every entry below is a",
        "# data point the device reported. Rename entities, fix units/scales",
        "# and delete what you do not need. The `tuya_name` key is Tuya's own",
        "# (Chinese) name for the DP and is informational only.",
        "# ====================================================",
    ]
    for category, var in _MODEL_VARS.items():
        items = discovered.get(category) or {}
        lines.append("")
        lines.append(f"{var} = {{")
        for key, cfg in items.items():
            clean = {k: v for k, v in cfg.items() if k not in _DROP_KEYS and v is not None}
            value = live.get(cfg.get("code", key), {}).get("value")
            lines.append(f"    # dp {cfg.get('dp_id')} — last value: {value!r}")
            lines.append(f"    {key!r}: {{")
            for k, v in clean.items():
                lines.append(f"        {k!r}: {v!r},")
            lines.append("    },")
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        sys.exit(1)
    dump_path = args[0]
    model_path = args[1] if len(args) > 1 else None

    schema, live, model_id = load_dump(dump_path)
    static_mapping = load_model_file(model_path)
    discovered = discovery.build_discovered_mapping(schema, live, static_mapping)

    if "--emit-model" in flags:
        print(emit_model(discovered, model_id, live))
        return

    print(f"Model ID      : {model_id}")
    print(f"Schema DPs    : {len(schema)}")
    print(f"Live DPs      : {len(live)}")
    if model_path:
        dp_ids, _ = discovery.static_coverage(static_mapping)
        print(f"Model file    : {os.path.basename(model_path)} covers {len(dp_ids)} DPs")
    print()

    total = discovery.count_entities(discovered)
    print(f"Discovery would add {total} entities:")
    for category in discovery.ENTITY_CATEGORIES:
        for key, cfg in discovered.get(category, {}).items():
            extra = ""
            if "options" in cfg:
                extra = f" options={list(cfg['options'])}"
            elif "min_value" in cfg:
                extra = f" range={cfg['min_value']}..{cfg['max_value']} step={cfg['step']}"
            unit = f" [{cfg['unit']}]" if cfg.get("unit") else ""
            value = live.get(cfg.get("code", key), {}).get("value")
            print(
                f"  {category.rstrip('es') if category.endswith('es') else category[:-1]:14s} {key:24s} dp={cfg.get('dp_id')!s:4s} "
                f"{cfg.get('tuya_access', ''):2s} {cfg.get('name', '')}{unit}{extra}  = {value!r}"
            )
            if cfg.get("tuya_name") and discovery._has_cjk(cfg["tuya_name"]):
                print(f"  {'':14s} {'':24s}        (tuya name: {cfg['tuya_name']})")

    merged = {
        c: {**static_mapping.get(c, {}), **discovered.get(c, {})}
        for c in discovery.ENTITY_CATEGORIES
    }
    leftovers = discovery.unmapped_codes(live, merged)
    print()
    print(f"Still unmapped live codes: {leftovers or 'none'}")
    static_dp_ids, _ = discovery.static_coverage(static_mapping)
    not_reported = sorted(
        p["code"] for p in schema.values()
        if p["code"] not in live and p["dp_id"] not in static_dp_ids
    )
    print(f"Schema DPs never reported: {not_reported or 'none'}")
    print()
    print("Tip: add --emit-model to print these as a model file skeleton.")


if __name__ == "__main__":
    main()
