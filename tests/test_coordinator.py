"""Regression tests for the coordinator, model loader and config
fingerprint (upstream 2.6.x port and its review fixes).

Needs Home Assistant installed (pip install homeassistant tinytuya
tuya-device-sharing-sdk pytest); skipped otherwise. Run from the repo
root: python -m pytest tests
"""
import asyncio, base64, struct, sys, types
from pathlib import Path

import pytest

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

def _sent(conn="local"):
    c = mk({"numbers": {"up": {"code":"up","api_conversion":"value * 10"},
                        "down": {"code":"down","api_conversion":"value / 10"}}})
    c.connection_type = conn; c._pending_commands = {}; c._sent_value_cache = {}
    c._debounce_delay = 0; c.data = {}; c.sent = []
    c._optimistic_update = lambda code, v: None
    return c

def test_int_normalization():
    # wire value after up-scale must be int; down-scale keeps float
    import inspect
    src = inspect.getsource(C.send_command)
    assert "_is_write_downscale" in src
    def norm(value, display):
        downscaled = (isinstance(display,(int,float)) and abs(value) < abs(display)) if isinstance(value,float) else False
        return int(value) if isinstance(value,float) and value.is_integer() and not downscaled else value
    assert norm(400.0, 40.0) == 400 and isinstance(norm(400.0, 40.0), int)
    assert isinstance(norm(4.0, 40.0), float)
    assert isinstance(norm(39.0, 39.0), int)

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
