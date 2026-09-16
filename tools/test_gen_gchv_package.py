#!/usr/bin/env python3
"""Checks for tools/gen_gchv_package.py.

Plain script, no test framework:

    python3 tools/test_gen_gchv_package.py

Prints one RESULT line per check and exits non-zero if any check failed.

Home Assistant derives a modbus or template entity's entity_id from its
*name*, slugified by homeassistant.util.slugify, not from its unique_id.

Check 1 pins literal entity ids that were derived with Home Assistant's own
slugify (core 2026.9.2 over python-slugify 8.0.4), independently of
gen.slug: each name must be emitted in its domain, gen.slug must reproduce
the literal, the raw-register ids must be what the templates reference, and
no reference may use the pre-fix unsuffixed form sensor.hp_gchv_r<n>. A
slug() that is wrong but self-consistent fails here.

Check 2 is the resolvability check: every sensor.* / binary_sensor.* the
package references must be the entity id of an entity the package emits in
that domain. It uses gen.slug for the defined side, so on its own it only
catches a reference and a definition that disagree; check 1 is what ties
gen.slug to Home Assistant. A reference is extracted up to the next quote
or whitespace, so a malformed id (say one containing a parenthesis) is kept
whole instead of being truncated into a valid prefix, and a reference that
is not a valid Home Assistant entity id counts as unresolved even when a
definition built by the same slug() matches it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

MODULE_PATH = pathlib.Path(__file__).resolve().parent / "gen_gchv_package.py"

_spec = importlib.util.spec_from_file_location("gen_gchv_package", MODULE_PATH)
gen = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(gen)

# Every reference in the package appears as states('<id>') or as a bare
# entity_id string, so an id ends at a quote or whitespace.
ENTITY_REF = re.compile(r"(?<![\w.])(binary_sensor|sensor)\.([^\s'\"]+)")

# (domain, emitted name, entity id Home Assistant derives). The ids were
# produced by homeassistant.util.slugify (core 2026.9.2, python-slugify
# 8.0.4), not by gen.slug. One row per punctuation class the package's names
# contain: space, parentheses, hyphen, slash, colon, degree sign.
HA_IDS = [
    ("sensor", "HP GCHV R404 (0194H)", "sensor.hp_gchv_r404_0194h"),
    ("sensor", "HP GCHV R44 (002CH)", "sensor.hp_gchv_r44_002ch"),
    ("sensor", "HP GCHV R4105 (1009H)", "sensor.hp_gchv_r4105_1009h"),
    ("sensor", "HP Entering water temperature (Tw-in)", "sensor.hp_entering_water_temperature_tw_in"),
    ("sensor", "HP Normal / Eco status", "sensor.hp_normal_eco_status"),
    ("binary_sensor", "HP ODU output: 4-way valve", "binary_sensor.hp_odu_output_4_way_valve"),
    ("number", "HP Water control point (°C)", "number.hp_water_control_point_degc"),
    ("number", "HP Booster OAT threshold (°C)", "number.hp_booster_oat_threshold_degc"),
]

# Raw-register ids the templates must reference (a subset of HA_IDS).
MUST_REFERENCE = ["sensor.hp_gchv_r404_0194h", "sensor.hp_gchv_r44_002ch", "sensor.hp_gchv_r4105_1009h"]

# homeassistant.core.VALID_ENTITY_ID (core 2026.9.2, homeassistant/core.py:180-183).
_OBJECT_ID = r"(?!_)[\da-z_]+(?<!_)"
VALID_ENTITY_ID = re.compile(r"^(?!.+__)" + _OBJECT_ID + r"\." + _OBJECT_ID + r"$")

# The pre-fix defect: a raw register referenced without its hex suffix.
UNSUFFIXED_RAW = re.compile(r"^sensor\.hp_gchv_r\d+$")

failures = 0


def result(ok: bool, text: str) -> None:
    global failures
    if not ok:
        failures += 1
    print(f"RESULT: {'PASS' if ok else 'FAIL'} - {text}")


def walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from walk_strings(k)
            yield from walk_strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from walk_strings(v)


def referenced_ids(package) -> set[str]:
    found = set()
    for text in walk_strings(package):
        found.update(f"{m.group(1)}.{m.group(2)}" for m in ENTITY_REF.finditer(text))
    return found


def emitted_names(package) -> dict[str, set[str]]:
    """domain -> names of the entities the package emits in that domain."""
    names: dict[str, set[str]] = {}
    for hub in package["modbus"]:
        names.setdefault("sensor", set()).update(s["name"] for s in hub.get("sensors", []))
    for block in package["template"]:
        for domain, entities in block.items():
            names.setdefault(domain, set()).update(e["name"] for e in entities)
    return names


def defined_ids(package) -> set[str]:
    return {f"{domain}.{gen.slug(n)}" for domain, ns in emitted_names(package).items() for n in ns}


def check_literal_ha_ids(package) -> None:
    names = emitted_names(package)
    referenced = referenced_ids(package)
    bad = []
    for domain, name, entity_id in HA_IDS:
        if name not in names.get(domain, set()):
            bad.append(f"{domain} {name!r} is not emitted by the package")
        got = f"{domain}.{gen.slug(name)}"
        if got != entity_id:
            bad.append(f"gen.slug({name!r}) gives {got}, Home Assistant gives {entity_id}")
    for entity_id in MUST_REFERENCE:
        if entity_id not in referenced:
            bad.append(f"{entity_id} is never referenced")
    unsuffixed = sorted(r for r in referenced if UNSUFFIXED_RAW.match(r))
    if unsuffixed:
        bad.append(f"{len(unsuffixed)} reference(s) use the unsuffixed raw form, e.g. {unsuffixed[0]}")
    for line in bad:
        print(f"    {line}")
    result(
        not bad,
        f"literal Home Assistant entity ids ({len(HA_IDS)} names, {len(MUST_REFERENCE)} required "
        f"references, {len(unsuffixed)} unsuffixed raw references)",
    )


def check_references_resolve(package) -> None:
    referenced = referenced_ids(package)
    defined = defined_ids(package)
    malformed = {r for r in referenced if not VALID_ENTITY_ID.match(r)}
    missing = sorted((referenced - defined) | malformed)
    if malformed:
        print(f"  {len(malformed)} referenced id(s) are not valid Home Assistant entity ids, e.g. {min(malformed)}")
    if missing:
        print(f"  {len(missing)} referenced entity id(s) are not defined by the package:")
        for entity_id in missing:
            print(f"    referenced but never defined: {entity_id}")
        near = sorted(d for d in defined if any(d.startswith(m) for m in missing))
        for d in near[:5]:
            print(f"    (the package does define: {d})")
    result(
        bool(referenced) and not missing,
        f"every referenced sensor.* / binary_sensor.* is defined by the package "
        f"({len(referenced)} referenced, {len(defined)} defined, {len(missing)} unresolved)",
    )


def check_raw_unique_ids_unchanged(package) -> None:
    """The fix must change the reference side only; these unique_ids are
    registered in existing installs and must not be renamed."""
    by_addr = {}
    for hub in package["modbus"]:
        for s in hub["sensors"]:
            by_addr[s["address"]] = s
    pins = {
        404: ("hp_gchv_r404", "HP GCHV R404 (0194H)"),
        44: ("hp_gchv_r44", "HP GCHV R44 (002CH)"),
        4105: ("hp_gchv_r4105", "HP GCHV R4105 (1009H)"),
    }
    bad = []
    for addr, (uid, name) in pins.items():
        s = by_addr.get(addr)
        if s is None:
            bad.append(f"address {addr} emits no modbus sensor at all")
            continue
        if s["unique_id"] != uid:
            bad.append(f"address {addr}: unique_id {s['unique_id']!r}, expected {uid!r}")
        if s["name"] != name:
            bad.append(f"address {addr}: name {s['name']!r}, expected {name!r}")
    for line in bad:
        print(f"    {line}")
    result(not bad, f"raw sensor names and unique_ids unchanged ({len(pins)} pinned)")


def main() -> int:
    package = gen.build()
    check_literal_ha_ids(package)
    check_references_resolve(package)
    check_raw_unique_ids_unchanged(package)
    print(f"{'FAILED' if failures else 'OK'}: {failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
