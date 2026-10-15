"""The Tuya Heatpump integration."""
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .coordinator import TuyaScaleDataUpdateCoordinator
from .model_loader import clear_model_cache
from .config_fingerprint import config_fingerprint
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

# get_device_info + get_device_model + ilk refresh için toplam üst sınır.
# Her adımın kendi içinde makul timeout'ları var (cloud istekleri 10sn,
# local status() ~7-8sn), ama HAOS açılışında ağ/DNS henüz tam hazır
# olmayabiliyor ve bunlar toplanabiliyor. Bu dış sınır, ne olursa olsun
# HA'nın açılışını (ya da bu entry'nin reload'unu) süresiz bekletmemesini
# garantiliyor — süre dolarsa ConfigEntryNotReady fırlatılır, HA bunu
# "biraz sonra tekrar dene" olarak ele alır (normal, beklenen davranış),
# boot akışını bloke eden asıl "sonsuza kadar takılı kalma" ihtimalini
# ortadan kaldırır.
# 25sn önceden dar geldiği için 45sn'e çıkarıldı (bkz. issue #77): üç
# adımın (get_device_info + get_device_model + first_refresh) her biri
# kendi timeout'una kadar sürebildiğinde toplam kolayca 25sn'i geçip
# yavaş ama aslında sağlıklı kurulumları ConfigEntryNotReady ile
# başarısız gösterebiliyordu.
SETUP_TIMEOUT = 45


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuya Heatpump from a config entry."""
    coordinator = TuyaScaleDataUpdateCoordinator(hass, entry)

    setup_started = asyncio.get_event_loop().time()

    def _elapsed() -> float:
        return asyncio.get_event_loop().time() - setup_started

    try:
        async with asyncio.timeout(SETUP_TIMEOUT):
            # Önce device info'yu al
            await coordinator.get_device_info()
            _LOGGER.debug("get_device_info tamamlandı (%.1fsn)", _elapsed())

            # Model bilgisini al
            await coordinator.get_device_model()
            _LOGGER.debug("get_device_model tamamlandı (%.1fsn)", _elapsed())

            await coordinator.async_config_entry_first_refresh()
            _LOGGER.debug("İlk refresh tamamlandı (%.1fsn)", _elapsed())

            # Live register discovery: now that we know both the device's
            # schema and what it actually reports, expose every data
            # point the model file left out (see discovery.py). Must run
            # before the platforms are forwarded so they see the merged
            # mapping.
            coordinator.apply_discovery()
    except asyncio.TimeoutError as err:
        # Local mode started its listener/heartbeat/poll tasks in the
        # coordinator's __init__; HA's retry builds a new coordinator, so
        # stop this attempt's tasks or they pile up (one socket each).
        await coordinator.async_close_local()
        raise ConfigEntryNotReady(
            f"Tuya Heat Pump setup timed out after {SETUP_TIMEOUT}s "
            f"(device_id={coordinator.device_id}, elapsed={_elapsed():.1f}s) — will retry"
        ) from err
    except BaseException:
        await coordinator.async_close_local()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Generic register read/write services (tuya_heat_pump.write_dp etc.),
    # registered once for all entries.
    async_setup_services(hass)

    # MQTT (tuya_sharing) — tamamen opsiyonel, bkz. sharing_mqtt.py.
    # Kullanıcı kurulumda User Code + QR onayı yapmadıysa (mevcut tüm
    # kurulumlar dahil) coordinator._async_start_mqtt() hiçbir şey
    # yapmadan hemen döner — davranış hiç değişmez. Model_mapping'in
    # kesin dolu olduğu (get_device_model + first_refresh tamamlandığı)
    # bu noktadan SONRA, arka planda (bloklamadan) başlatılıyor.
    mqtt_start = hass.loop.create_task(coordinator._async_start_mqtt())
    # Retrieve any exception so asyncio does not log it as never retrieved.
    mqtt_start.add_done_callback(lambda t: t.cancelled() or t.exception())

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException as err:
        # HA does not call unload for a failed setup: clean up here.
        # Let the start finish (cancelling the task cannot stop its
        # executor thread) so the stop below sees the MQTT client.
        await asyncio.wait({mqtt_start}, timeout=30 if not isinstance(err, asyncio.CancelledError) else 1)
        if coordinator.sharing_mqtt is not None:
            await coordinator.sharing_mqtt.async_stop()
        # Platforms that did load stay registered otherwise (HA does not
        # call unload for a failed setup); unloading one that never loaded
        # raises, so go one by one.
        for platform in PLATFORMS:
            try:
                await hass.config_entries.async_forward_entry_unload(entry, platform)
            except Exception as unload_err:  # e.g. platform never loaded
                _LOGGER.debug("Unload of %s skipped: %s", platform, unload_err)
        await coordinator.async_close_local()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        clear_model_cache(coordinator.model_id)
        if not hass.data[DOMAIN]:
            async_unload_services(hass)
        raise

    entry.async_on_unload(entry.add_update_listener(async_update_options))
    # A settings change saved during setup, before the listener existed,
    # would otherwise only apply on the next restart.
    if config_fingerprint(entry) != coordinator.applied_config:
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    return True

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options.

    Not: bu listener entry.options KADAR entry.data değişimlerinde de
    tetikleniyor (HA'nın add_update_listener davranışı ikisini de
    kapsıyor). sharing_mqtt.py token'ı persist ederken (~2 saatte bir,
    otomatik yenileme) entry.data'yı güncelliyor — bu bir kullanıcı
    ayar değişikliği DEĞİL, o yüzden reload gerektirmiyor: the listener
    compares the entry against coordinator.applied_config, which leaves
    the cache-only keys out (config_fingerprint.py).
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        # Not loaded (mid-unload, or removed): the next setup reads the
        # current settings anyway.
        return
    fingerprint = config_fingerprint(entry)
    if fingerprint == coordinator.applied_config:
        _LOGGER.debug("Only cache keys changed in the config entry — no reload.")
        return
    # Mark this change as handled before reloading: one save can update
    # data and options separately and queue this listener twice.
    coordinator.applied_config = fingerprint
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TuyaScaleDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_close_local()
        if coordinator.sharing_mqtt is not None:
            await coordinator.sharing_mqtt.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id)
        # Re-read an edited model file on the next setup instead of only
        # after a full HA restart.
        clear_model_cache(coordinator.model_id)
        if not hass.data[DOMAIN]:
            async_unload_services(hass)

    return unload_ok
