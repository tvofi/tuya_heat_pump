"""
Register discovery preview
==========================
Shows, offline, which extra Home Assistant entities the integration's
live register discovery (custom_components/tuya_heat_pump/discovery.py)
would create for a device -- without touching Home Assistant.

Feed it the ``tuya_device_data_<timestamp>.txt`` file written by
``tuya_api_test.py`` (it contains both the live properties and the
device's full Tuya model/schema):

    python discovery_preview.py tuya_device_data_20260707_224248.txt

Optionally compare against a model file so you only see what the model
does NOT already cover:

    python discovery_preview.py tuya_device_data_....txt \
        ../custom_components/tuya_heat_pump/models/000004k4z6.py

Output: one line per entity with platform, key, DP id, name, unit and
the conversion used, followed by the list of DPs that are still
unmapped (e.g. schema entries the device never reported).

Requirements: none beyond the standard library.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
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


def load_dump(path: str) -> tuple[dict, dict]:
    """Return (properties_result, model_info) from a tuya_api_test dump
    or from a plain JSON file with those two documents."""
    text = open(path, encoding="utf-8").read()
    properties = {}
    model_info = {}
    for block in _extract_json_blocks(text):
        result = block.get("result", block)
        if isinstance(result, dict) and "properties" in result:
            properties = result
        if isinstance(result, dict) and "model" in result:
            model_str = result["model"]
            try:
                model_info = json.loads(model_str) if isinstance(model_str, str) else model_str
            except json.JSONDecodeError:
                pass
        if "services" in block:
            model_info = block
    return properties, model_info


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


def live_data_from_properties(properties: dict) -> dict:
    data = {}
    for prop in properties.get("properties", []) or []:
        code = prop.get("code")
        if not code:
            continue
        data[code] = {
            "value": prop.get("value"),
            "type": prop.get("type", ""),
            "dp_id": prop.get("dp_id"),
        }
    return data


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    dump_path = sys.argv[1]
    model_path = sys.argv[2] if len(sys.argv) > 2 else None

    properties, model_info = load_dump(dump_path)
    schema = discovery.parse_device_schema(model_info)
    live = live_data_from_properties(properties)
    static_mapping = load_model_file(model_path)

    print(f"Model ID      : {model_info.get('modelId', '?')}")
    print(f"Schema DPs    : {len(schema)}")
    print(f"Live DPs      : {len(live)}")
    if model_path:
        dp_ids, codes = discovery.static_coverage(static_mapping)
        print(f"Model file    : {os.path.basename(model_path)} covers {len(dp_ids)} DPs")
    print()

    discovered = discovery.build_discovered_mapping(schema, live, static_mapping)
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
            print(
                f"  {category[:-1]:14s} {key:24s} dp={cfg.get('dp_id')!s:4s} "
                f"{cfg.get('tuya_access', ''):2s} {cfg.get('name', '')}{unit}{extra}"
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
    not_reported = sorted(
        p["code"] for p in schema.values()
        if p["code"] not in live and p["dp_id"] not in discovery.static_coverage(static_mapping)[0]
    )
    print(f"Schema DPs never reported: {not_reported or 'none'}")


if __name__ == "__main__":
    main()
