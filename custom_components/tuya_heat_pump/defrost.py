"""Defrost state for heat pumps whose Tuya data carries no defrost status.

Some units expose only a *forced defrost* command over Tuya (the Rotenso
Windmi: dp 102 ``DEF``, 强制除霜, read/write) and nothing that reports the
controller's own automatic defrost cycles. Two sources fill that gap:

1. An external binary sensor chosen in the integration options (for
   example a Modbus sensor on the unit's running-mode register; see
   docs/modbus/README.md). When set, it is the only source.
2. Otherwise a heuristic, driven by a model file's ``DEFROST_DETECTION``
   dict. A reverse-cycle defrost pulls heat out of the water loop, so
   the leaving water falls below the entering water while the unit is
   in a heating mode, and the outdoor coil warms up.

The heuristic, per coordinator update:

* ``supply - return <= DEFROST_DELTA_T_K`` while the mode is one of the
  model's heating modes counts as one defrost sample;
* ``DEFROST_CONSECUTIVE_SAMPLES`` samples in a row switch it on;
* if any confirm input (coil / outdoor temperature) has data, entry also
  needs one of them to have risen by ``DEFROST_CONFIRM_RISE_K`` or more
  over the last ``DEFROST_CONFIRM_LOOKBACK`` samples. With no confirm
  data the water condition alone decides;
* it switches off on the first sample that no longer meets the water
  condition (or leaves the heating modes).

Updates closer together than ``DEFROST_MIN_SAMPLE_SPACING_S`` (a burst of
pushed DPs, a write echo, a calibration change) re-evaluate the latest
sample instead of counting as a new one.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable

# Leaving minus entering water at or below this (kelvin) is a defrost sample.
DEFROST_DELTA_T_K = -1.0
# Consecutive defrost samples needed to switch on.
DEFROST_CONSECUTIVE_SAMPLES = 2
# Rise (kelvin) of a confirm input that confirms entry.
DEFROST_CONFIRM_RISE_K = 2.0
# Samples looked back over for that rise (before and during the streak).
DEFROST_CONFIRM_LOOKBACK = 4
# Updates closer together than this (seconds) are one sample.
DEFROST_MIN_SAMPLE_SPACING_S = 20.0

SOURCE_HEURISTIC = "heuristic"
SOURCE_ENTITY = "entity"


class DefrostDetector:
    """Stateful defrost heuristic for one device."""

    def __init__(self, config: dict) -> None:
        self.mode_code: str = config.get("mode", "mode")
        self.heating_modes = frozenset(config.get("heating_modes", ()))
        self.supply_code: str = config["supply"]
        self.return_code: str = config["return"]
        self.confirm_codes: tuple[str, ...] = tuple(config.get("confirm", ()))
        self.delta_t_k = float(config.get("delta_t_k", DEFROST_DELTA_T_K))
        self.samples_needed = int(config.get("consecutive_samples", DEFROST_CONSECUTIVE_SAMPLES))
        self.confirm_rise_k = float(config.get("confirm_rise_k", DEFROST_CONFIRM_RISE_K))
        lookback = int(config.get("confirm_lookback", DEFROST_CONFIRM_LOOKBACK))
        self.min_spacing_s = float(config.get("min_sample_spacing_s", DEFROST_MIN_SAMPLE_SPACING_S))

        self.active: bool | None = None
        self.confirmed: bool | None = None
        self._streak = 0
        self._last_sample_at: float | None = None
        # Confirm history: one dict of {code: value} per counted sample,
        # including the current one (replaced in place on a re-evaluation).
        self._history: deque[dict[str, float]] = deque(maxlen=lookback + 1)

    @property
    def inputs(self) -> tuple[str, ...]:
        """Model sensor codes the detector reads."""
        return (self.mode_code, self.supply_code, self.return_code, *self.confirm_codes)

    def _is_sample(self, mode: Any, supply: Any, ret: Any) -> bool | None:
        """True/False for a defrost sample, None when the inputs are missing."""
        if mode is None or supply is None or ret is None:
            return None
        if mode not in self.heating_modes:
            return False
        try:
            return float(supply) - float(ret) <= self.delta_t_k
        except (TypeError, ValueError):
            return None

    def _rise_seen(self) -> bool | None:
        """Whether a confirm input rose enough; None when none has data."""
        any_data = False
        for code in self.confirm_codes:
            values = [s[code] for s in self._history if code in s]
            if not values:
                continue
            any_data = True
            current = values[-1]
            if current - min(values) >= self.confirm_rise_k:
                return True
        return False if any_data else None

    def update(self, read: Callable[[str], Any], now: float) -> bool | None:
        """Feed one coordinator update; return the new state.

        ``read(code)`` returns the converted value of a model sensor (or
        the raw value of an enum DP such as the mode), None when missing.
        """
        new_sample = (
            self._last_sample_at is None
            or now - self._last_sample_at >= self.min_spacing_s
        )
        confirm = {}
        for code in self.confirm_codes:
            value = read(code)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                confirm[code] = float(value)
        if new_sample:
            self._history.append(confirm)
            self._last_sample_at = now
        elif self._history:
            self._history[-1] = confirm
        else:
            self._history.append(confirm)

        sample = self._is_sample(read(self.mode_code), read(self.supply_code), read(self.return_code))
        if sample is None:
            # Missing inputs: unknown, and the streak starts over.
            self._streak = 0
            self.active = None
            self.confirmed = None
            return None
        if not sample:
            self._streak = 0
            self.active = False
            self.confirmed = None
            return False

        if new_sample or self._streak == 0:
            self._streak += 1
        if self.active:
            # Already on: stays on while the water condition holds.
            return True
        if self._streak < self.samples_needed:
            self.active = False
            return False
        rise = self._rise_seen()
        if rise is False:
            # Confirm data exists and shows no warming: not a defrost
            # (e.g. a DHW valve change-over with a colder tank).
            self.active = False
            self.confirmed = False
            return False
        self.active = True
        self.confirmed = rise  # True, or None when unconfirmable
        return True


def external_state(state: Any) -> bool | None:
    """Map a Home Assistant state object of the chosen entity to on/off."""
    if state is None:
        return None
    value = getattr(state, "state", None)
    if value == "on":
        return True
    if value == "off":
        return False
    return None

