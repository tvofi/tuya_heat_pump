#!/usr/bin/env python3
"""Checks for tools/gen_gchv_package.py.

Plain script, no test framework:

    python3 tools/test_gen_gchv_package.py

Prints one RESULT line per check and exits non-zero if any check failed.

Check 1 is the one that matters: Home Assistant derives a modbus sensor's
entity_id from its *name* (slugified), not from its unique_id, so every
`sensor.*` the generated templates reference must be the slug of a name the
package actually emits. The slug rule is imported from the module under test
rather than re-implemented here, so the two cannot drift apart silently.
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

SENSOR_REF = re.compile(r"sensor\.[a-z0-9_]+")

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


def referenced_sensor_ids(package) -> set[str]:
    found = set()
    for text in walk_strings(package):
        found.update(SENSOR_REF.findall(text))
    return found


def defined_sensor_ids(package) -> set[str]:
    defined = set()
    for hub in package["modbus"]:
        for s in hub["sensors"]:
            defined.add("sensor." + gen.slug(s["name"]))
    for block in package["template"]:
        for domain in ("sensor", "binary_sensor"):
            for e in block.get(domain, []):
                defined.add("sensor." + gen.slug(e["name"]))
    return defined


def check_references_resolve(package) -> None:
    referenced = referenced_sensor_ids(package)
    defined = defined_sensor_ids(package)
    missing = sorted(referenced - defined)
    if missing:
        print(f"  {len(missing)} referenced entity id(s) are not defined by the package:")
        for entity_id in missing:
            print(f"    referenced but never defined: {entity_id}")
        near = sorted(d for d in defined if any(d.startswith(m) for m in missing))
        for d in near[:5]:
            print(f"    (the package does define: {d})")
    result(
        not missing,
        f"every referenced sensor.* is defined by the package "
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
    check_references_resolve(package)
    check_raw_unique_ids_unchanged(package)
    print(f"{'FAILED' if failures else 'OK'}: {failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
