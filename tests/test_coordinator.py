"""Regression tests for the coordinator, model loader and config
fingerprint (upstream 2.6.x port and its review fixes).

Needs Home Assistant installed (pip install homeassistant tinytuya
tuya-device-sharing-sdk pytest); skipped otherwise. Run from the repo
root: python -m pytest tests
"""
import asyncio, base64, struct, sys, types
from pathlib import Path

import pytest

import os
if os.environ.get("TUYA_HP_REQUIRE_HA"):
    import homeassistant  # noqa: F401  CI: a broken HA import must fail, not skip
else:
    pytest.importorskip("homeassistant")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib
pkg = "custom_components.tuya_heat_pump"
for m in ["__init__","coordinator","climate","config_flow","sensor","binary_sensor","number","select","switch","model_loader","raw_codec"]:
    importlib.import_module(f"{pkg}.{m}" if m!="__init__" else pkg)
from custom_components.tuya_heat_pump.coordinator import TuyaScaleDataUpdateCoordinator as C
from custom_components.tuya_heat_pump import model_loader, raw_codec

def mk(mapping):
    c = C.__new__(C); c.model_mapping = mapping; c._pending_commands = {}; c._closing = False; c._local_closed = False; c._sending_codes = {}; return c

def test_resolve_cache():
    c = mk({"numbers": {"a": {"code":"a","conversion":"value / 10","api_conversion":"int(value*10)"},
                        "b": {"code":"b","api_conversion":"value / 10"}}})
    assert c._resolve_cache_value("a", 260, 26.0) == 260
    assert c._resolve_cache_value("b", 4.0, 40.0) == 40.0
    assert c._resolve_cache_value("x", 5, 5) == 5

def test_byte_offset():
    p = base64.b64encode(b"\x00" + struct.pack(">h", 215)).decode()
    assert raw_codec.decode_raw_field(p, 0, "int16_be", byte_offset=1) == 215

def test_clear_cache():
    model_loader._MODEL_CACHE["zz"] = {}
    sys.modules[f"{pkg}.models.zz"] = types.ModuleType("zz")
    model_loader.clear_model_cache("zz")
    assert "zz" not in model_loader._MODEL_CACHE and f"{pkg}.models.zz" not in sys.modules

def test_cancel_tasks():
    async def run():
        c = mk({})
        async def forever(): await asyncio.sleep(100)
        ts = [asyncio.ensure_future(forever()) for _ in range(4)]
        c._start_listener_task, c._listener_task, c._heartbeat_task, c._fallback_poll_task = ts
        c.cancel_background_tasks(); await asyncio.sleep(0)
        assert all(t.cancelled() for t in ts)
        c2 = mk({}); c2._start_listener_task=c2._listener_task=c2._heartbeat_task=c2._fallback_poll_task=None
        c2.cancel_background_tasks()
    asyncio.run(run())

def test_write_priority():
    import threading
    c = mk({}); c._write_pending = threading.Event(); c._write_pending.set()
    assert c._local_heartbeat() is None and c._local_receive() is None

def _local_coord(mapping):
    """Bare coordinator wired for the local send path (no device I/O)."""
    c = mk(mapping)
    c.connection_type = "local"; c._debounce_delay = 0
    c._sent_value_cache = {}; c.data = {}
    c.dp_mapping = {1: "up", 2: "down", 3: "plain", 4: "f"}
    c._optimistic_update = lambda code, v: None
    sent = []
    class Hass:
        loop = None
        async def async_add_executor_job(self, f, *a): return f(*a)
    c.hass = Hass()
    c._local_set_value = lambda dp, v: sent.append((dp, v)) or True
    c.local_device = object()
    return c, sent

def test_send_command_wire_types():
    """Real send_command: up-scaled and unit-converted writes go out as
    int (issue #80); a plain 'value / N' down-scale keeps the float
    (upstream issue #53)."""
    mapping = {"numbers": {
        "up": {"code": "up", "api_conversion": "value * 10"},
        "down": {"code": "down", "api_conversion": "value / 10"},
        "plain": {"code": "plain"},
        "f": {"code": "f", "api_conversion": "(value * 9/5) + 32"},
    }}
    async def run():
        c, sent = _local_coord(mapping)
        c.hass.loop = asyncio.get_running_loop()
        assert await c.send_command("up", 400.0, display_value=40.0)
        assert await c.send_command("down", 4.0, display_value=40.0)
        assert await c.send_command("plain", 39.0)
        assert await c.send_command("f", -4.0, display_value=-20.0)
        for _ in range(5):
            await asyncio.sleep(0.01)
        got = dict(sent)
        assert got[1] == 400 and type(got[1]) is int
        assert got[2] == 4.0 and type(got[2]) is float
        assert got[3] == 39 and type(got[3]) is int
        assert got[4] == -4 and type(got[4]) is int
    asyncio.run(run())

def test_merge_heartbeat_frame():
    c = mk({}); c.data = {"a": {"value": 1}}; got = []
    c._process_local_dps = lambda dps: {"b": {"value": dps["2"]}}
    c._apply_sent_cache = lambda d: None
    c.async_set_updated_data = got.append
    c._merge_pushed_frame(None); c._merge_pushed_frame({"dps": {"2": 5}})
    assert got == [{"a": {"value": 1}, "b": {"value": 5}}]

def test_cancel_pending_writes():
    async def run():
        c = mk({}); c._start_listener_task=c._listener_task=c._heartbeat_task=c._fallback_poll_task=None
        t = asyncio.ensure_future(asyncio.sleep(100)); c._pending_commands = {"x": (1, t)}
        c.cancel_background_tasks(); await asyncio.sleep(0)
        assert t.cancelled() and c._pending_commands == {}
    asyncio.run(run())

def test_fallback_keeps_data_on_failure():
    from homeassistant.helpers.update_coordinator import UpdateFailed
    async def run():
        c = mk({}); c.data = None; c._FALLBACK_POLL_INTERVAL = 0; calls = []; got = []
        async def upd():
            calls.append(1)
            if len(calls) == 1: raise UpdateFailed("x")
            if len(calls) == 3: raise asyncio.CancelledError
            return {"a": 1}
        c._async_update_data = upd; c.async_set_updated_data = got.append
        try: await c._fallback_poll_loop()
        except asyncio.CancelledError: pass
        assert got == [{"a": 1}]
    asyncio.run(run())

def test_downscale_from_model():
    c = mk({"numbers": {"f": {"code":"f","api_conversion":"(value * 9/5) + 32"},
                        "d": {"code":"d","api_conversion":"value / 10"},
                        "u": {"code":"u","api_conversion":"value * 10"}}})
    assert c._is_write_downscale("d") and not c._is_write_downscale("f") and not c._is_write_downscale("u")

def test_close_local_flushes_and_closes():
    async def run():
        class Hass:
            async def async_add_executor_job(self, f, *a): return f(*a)
        c = mk({}); c.hass = Hass(); c.connection_type = "local"
        c._start_listener_task=c._listener_task=c._heartbeat_task=c._fallback_poll_task=None
        sent=[]; closed=[]
        c._local_set_value = lambda dp, v: sent.append((dp, v)) or True
        import threading
        c._local_socket_lock = threading.Lock(); c._LOCK_ACQUIRE_TIMEOUT = 1
        class Dev:
            def close(self): closed.append(1)
        c.local_device = Dev(); c.dp_mapping = {7: "x"}
        t = asyncio.ensure_future(asyncio.sleep(100)); c._pending_commands = {"x": (42, t)}
        await c.async_close_local(); await c.async_close_local()
        assert sent == [(7, 42)] and closed == [1] and c.local_device is None
    asyncio.run(run())

def test_default_reload():
    import importlib
    m = importlib.import_module(f"{pkg}.models.default")
    model_loader._MODEL_SOURCE["unknownx"] = m.__name__
    model_loader.clear_model_cache("unknownx")
    assert m.__name__ not in sys.modules
    mp = model_loader.load_model_mapping("default")
    assert f"{pkg}.models.default" in sys.modules and mp["numbers"]

def test_downscale_shared_sensor_code():
    c = mk({"sensors": {"temp_set": {"code": "temp_set"}},
            "numbers": {"temp_set": {"code": "temp_set", "api_conversion": "value / 10"}}})
    assert c._is_write_downscale("temp_set")

def test_refuse_writes_while_closing():
    c = mk({}); c._closing = True
    assert asyncio.run(c.send_command("x", 1)) is False

def test_closed_wrapper_raises():
    import threading, pytest
    c = mk({}); c._local_socket_lock = threading.Lock(); c._LOCK_ACQUIRE_TIMEOUT = 1
    c._local_closed = True; c.local_device = object()
    with pytest.raises(ConnectionError):
        c._local_status()

def test_clear_cache_aliases():
    p = f"{pkg}.models.default"
    model_loader._MODEL_SOURCE.update({"a1": p, "a2": p})
    model_loader._MODEL_CACHE.update({"a1": {}, "a2": {}})
    model_loader.clear_model_cache("a1")
    assert "a2" not in model_loader._MODEL_CACHE


def test_fingerprint_ignores_cache_keys():
    from custom_components.tuya_heat_pump.config_fingerprint import config_fingerprint
    E = types.SimpleNamespace
    base = E(data={"ip": "1.2.3.4", "cached_access_token": "a"}, options={"x": 1})
    assert config_fingerprint(base) == config_fingerprint(
        E(data={"ip": "1.2.3.4", "cached_access_token": "b", "sharing_token_info": {}}, options={"x": 1}))
    assert config_fingerprint(base) != config_fingerprint(
        E(data={"ip": "5.6.7.8", "cached_access_token": "a"}, options={"x": 1}))
    assert config_fingerprint(base) != config_fingerprint(
        E(data={"ip": "1.2.3.4", "cached_access_token": "a"}, options={"x": 2}))

def test_write_waits_for_previous_send():
    async def run():
        c = mk({}); order = []
        async def slow_a():
            await asyncio.sleep(0.05); order.append("a")
        a = asyncio.ensure_future(slow_a()); c._sending_codes["x"] = a
        await c._async_wait_previous_send("x"); order.append("b")
        assert order == ["a", "b"]
    asyncio.run(run())

def test_mqtt_start_aborts_after_stop():
    from custom_components.tuya_heat_pump.sharing_mqtt import SharingMQTT
    async def run():
        m = SharingMQTT.__new__(SharingMQTT)
        m._manager = None; m._health_check_task = None; m._stopped = False
        assert await m._abort_if_stopped() is False
        await m.async_stop()
        assert await m._abort_if_stopped() is True
    asyncio.run(run())


def _entry(data, options, entry_id="e1"):
    return types.SimpleNamespace(entry_id=entry_id, data=data, options=options)

def _listener_hass(coordinator, entry_id="e1"):
    from custom_components.tuya_heat_pump.const import DOMAIN
    reloads = []
    async def async_reload(eid): reloads.append(eid)
    hass = types.SimpleNamespace(
        data={DOMAIN: {entry_id: coordinator} if coordinator else {}},
        config_entries=types.SimpleNamespace(async_reload=async_reload),
    )
    return hass, reloads

def test_update_listener_branches():
    from custom_components.tuya_heat_pump import async_update_options
    from custom_components.tuya_heat_pump.config_fingerprint import config_fingerprint
    async def run():
        start = _entry({"ip": "1.2.3.4"}, {"x": 1})
        coord = types.SimpleNamespace(applied_config=config_fingerprint(start))
        # cache-only change: no reload
        hass, reloads = _listener_hass(coord)
        await async_update_options(hass, _entry({"ip": "1.2.3.4", "cached_access_token": "t"}, {"x": 1}))
        assert reloads == []
        # real change: one reload, and the same change queued twice reloads once
        changed = _entry({"ip": "5.6.7.8"}, {"x": 1})
        await async_update_options(hass, changed)
        await async_update_options(hass, changed)
        assert reloads == ["e1"]
        # no coordinator (unloaded): no reload
        hass, reloads = _listener_hass(None)
        await async_update_options(hass, changed)
        assert reloads == []
    asyncio.run(run())

def test_start_local_false_opens_no_socket(tmp_path):
    """Validation coordinator: no tinytuya device, no background tasks."""
    from homeassistant.core import HomeAssistant
    from custom_components.tuya_heat_pump.const import CONF_CONNECTION_TYPE
    async def run():
        from homeassistant.helpers import frame
        hass = HomeAssistant(str(tmp_path))
        frame.async_setup(hass)
        entry = types.SimpleNamespace(entry_id=None, options={}, data={
            CONF_CONNECTION_TYPE: "local", "device_id": "d", "access_id": "a",
            "access_key": "k", "region": "eu", "ip": "10.0.0.9",
            "local_key": "0123456789abcdef", "protocol": "3.4",
        })
        c = C(hass, entry, start_local=False)
        assert c.local_device is None
        assert c._start_listener_task is None and c._listener_task is None
        await c.async_close_local()
        await hass.async_stop(force=True)
    asyncio.run(run())

def test_flush_respects_deadline_and_cancels():
    """A stuck older write must not eat the flush deadline forever; a
    flush still running at the deadline is cancelled, not orphaned."""
    async def run():
        c, sent = _local_coord({})
        c.hass.loop = asyncio.get_running_loop()
        c._FLUSH_PREV_WAIT = 0.05
        import threading
        c._local_socket_lock = threading.Lock(); c._LOCK_ACQUIRE_TIMEOUT = 1
        c._start_listener_task = c._listener_task = c._heartbeat_task = c._fallback_poll_task = None
        stuck = asyncio.ensure_future(asyncio.sleep(100))
        c._sending_codes["plain"] = stuck          # older write that never ends
        pending = asyncio.ensure_future(asyncio.sleep(100))
        c._pending_commands = {"plain": (7, pending)}
        class Dev:
            def close(self): pass
        c.local_device = Dev()
        await asyncio.wait_for(c.async_close_local(), timeout=5)
        assert sent == [(3, 7)]
        stuck.cancel()
    asyncio.run(run())


def test_flush_cancelled_at_deadline():
    """A flush whose set_value never returns is cancelled at the deadline."""
    async def run():
        c, sent = _local_coord({})
        c.hass.loop = asyncio.get_running_loop()
        c._FLUSH_PREV_WAIT = -11.9   # deadline = 0.1 s
        import threading
        c._local_socket_lock = threading.Lock(); c._LOCK_ACQUIRE_TIMEOUT = 1
        c._start_listener_task = c._listener_task = c._heartbeat_task = c._fallback_poll_task = None
        started = []
        class Hass:
            loop = asyncio.get_running_loop()
            async def async_add_executor_job(self, f, *a):
                if f == c._local_set_value:
                    started.append(1); await asyncio.sleep(100)
                return f(*a)
        c.hass = Hass()
        c._pending_commands = {"plain": (7, asyncio.ensure_future(asyncio.sleep(100)))}
        class Dev:
            def close(self): pass
        c.local_device = Dev()
        await asyncio.wait_for(c.async_close_local(), timeout=5)
        await asyncio.sleep(0)
        assert started == [1] and c.local_device is None
        assert not [t for t in asyncio.all_tasks()
                    if t is not asyncio.current_task() and "flush" in repr(t.get_coro())]
    asyncio.run(run())

def test_reload_failure_restores_applied_config():
    from custom_components.tuya_heat_pump import async_update_options
    from custom_components.tuya_heat_pump.config_fingerprint import config_fingerprint
    async def run():
        start = _entry({"ip": "1.2.3.4"}, {})
        coord = types.SimpleNamespace(applied_config=config_fingerprint(start))
        hass, _ = _listener_hass(coord)
        async def boom(eid): raise RuntimeError("reload failed")
        hass.config_entries.async_reload = boom
        with pytest.raises(RuntimeError):
            await async_update_options(hass, _entry({"ip": "5.6.7.8"}, {}))
        assert coord.applied_config == config_fingerprint(start)
    asyncio.run(run())
