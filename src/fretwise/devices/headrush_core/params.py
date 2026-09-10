"""Convert HeadRush Core parameters between device floats and display units.

Every continuous parameter on the device is a float in ``0.0..1.0``. What a human
(and a tone sheet) wants to say is ``300 ms``, ``-3 dB``, ``85 Hz``. The mapping
between the two is published per parameter by ``object-meta``: ``minimum`` and
``maximum`` in *display* units, an optional ``x-options.normalizeAlgo`` selecting
the curve, plus ``format`` and ``grid``.

The eleven curves below are transcribed from the device's own web editor bundle —
its ``xf`` (display to normalized) and ``Af`` (normalized to display) tables — so
that FretWise writes the value the device's own UI would have written. Two details
of that transcription matter:

* the normalize direction applies ``Math.fround`` (float32); the denormalize
  direction does not. Reproducing this is the difference between a clean
  round-trip and a drift in the seventh digit;
* ``normalizeAlgo == 3`` (``DelayRatio``) is declared in the bundle's enum but has
  **no entry in either table**, so the editor silently falls back to Linear for it.
  Rather than copy a bug, :func:`to_normalized` refuses that parameter. Measured on
  firmware 5.1.0.2a63755: **no parameter actually uses algo 3**, so the guard costs
  nothing today and protects against a future firmware that starts using it.

Only five curves are used by this firmware — Linear (5691 params), Exponential
(906), Squared (58), H3Volume (4), H3ReverbTime (2). The other six are implemented
for fidelity but are **not exercised by any real parameter**, and the parity test
says so rather than pretending they are covered.
"""

from __future__ import annotations

import math
import struct
from typing import Any

from fretwise.devices.headrush_core.catalog import ParamSchema

# Constants transcribed verbatim from the editor bundle.
_VF = 0.044282303954338874
_EF = -14 / 0.75


def _yf(value: float) -> float:
    return math.pow(10.0, 0.05 * value)


_WF = _yf(-14)
_SF = _WF / 0.25

#: Curve ids, matching the bundle's enum order.
LINEAR = 0
DB = 1
VOLUME = 2
DELAY_RATIO = 3
TIME_BI_SQUARED = 4
SQUARED = 5
EXPONENTIAL = 6
MIXER_GAIN = 7
H3_VOLUME = 8
ALLEN_HEATH_FADER_VOLUME = 9
H3_REVERB_TIME = 10

#: Human names, for error messages and reports.
ALGO_NAMES: dict[int, str] = {
    LINEAR: "Linear",
    DB: "Db",
    VOLUME: "Volume",
    DELAY_RATIO: "DelayRatio",
    TIME_BI_SQUARED: "TimeBiSquared",
    SQUARED: "Squared",
    EXPONENTIAL: "Exponential",
    MIXER_GAIN: "MixerGain",
    H3_VOLUME: "H3Volume",
    ALLEN_HEATH_FADER_VOLUME: "AllenHeathFaderVolume",
    H3_REVERB_TIME: "H3ReverbTime",
}

#: Curves this firmware actually uses; the rest are implemented but untested
#: against real data. Keep in sync with the catalog when a firmware changes.
ALGOS_IN_USE: frozenset[int] = frozenset({LINEAR, SQUARED, EXPONENTIAL, H3_VOLUME, H3_REVERB_TIME})


class ParamError(ValueError):
    """A parameter cannot be converted or is out of contract."""


def fround(value: float) -> float:
    """Return ``value`` rounded to the nearest float32, like JavaScript's Math.fround."""
    return float(struct.unpack("f", struct.pack("f", value))[0])


def _bounds(param: ParamSchema) -> tuple[float, float]:
    """Return ``(minimum, maximum)`` in display units, defaulting a missing bound to 0/1."""
    low = param.minimum if param.minimum is not None else 0.0
    high = param.maximum if param.maximum is not None else 1.0
    return low, high


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else (high if value > high else value)


# --- display -> normalized (the bundle's xf table) ---------------------------


def _xf(algo: int, value: float, low: float, high: float) -> float:
    if algo == DB:
        return (value - low) / (2 * -low) if value <= 0 else 0.5 + value / (2 * high)
    if algo == VOLUME:
        return math.pow(10.0, 0.05 * value)
    if algo == TIME_BI_SQUARED:
        ratio = abs(value) / high
        ratio = 1.0 if ratio > 1 else math.sqrt(ratio)
        return 0.5 + 0.5 * (-ratio if value < 0 else ratio)
    if algo == SQUARED:
        clamped = _clamp(value, low, high)
        return 0.0 if high == low else math.sqrt((clamped - low) / (high - low))
    if algo == EXPONENTIAL:
        return math.log(value / low) / math.log(high / low)
    if algo == MIXER_GAIN:
        return math.log(value / _VF + 1) / 4.515
    if algo == H3_VOLUME:
        if value <= -200:
            return 0.0
        return high if value > high else math.pow(10.0, 0.05 * (value - high))
    if algo == ALLEN_HEATH_FADER_VOLUME:
        return 1 - (20 * math.log10(value) / _EF) if value > _WF else value / _SF
    if algo == H3_REVERB_TIME:
        return 1.0 if value > 144 else (value - 0.45) / (1 + value)
    return (value - low) / (high - low)  # LINEAR


# --- normalized -> display (the bundle's Af table) ---------------------------


def _af(algo: int, value: float, low: float, high: float) -> float:
    if algo == DB:
        return low + 2 * value * -low if value <= 0.5 else high * (value - 0.5) * 2
    if algo == VOLUME:
        return 20 * math.log10(value)
    if algo == TIME_BI_SQUARED:
        n = 2 * value - 1
        return n * n * (-high if n < 0 else high)
    if algo == SQUARED:
        return low + (high - low) * value * value
    if algo == EXPONENTIAL:
        return low * math.exp(math.log(high / low) * value)
    if algo == MIXER_GAIN:
        return _VF * (math.exp(4.515 * value) - 1)
    if algo == H3_VOLUME:
        return high + 20 * math.log10(max(value, 1e-10))
    if algo == ALLEN_HEATH_FADER_VOLUME:
        return _yf((1 - value) * _EF) if value > 0.25 else value * _SF
    if algo == H3_REVERB_TIME:
        return 145.0 if value > fround(0.99) else (0.45 + value) / (1 - value)
    return (high - low) * value + low  # LINEAR


# --- public API --------------------------------------------------------------


def to_display(param: ParamSchema, normalized: float) -> float:
    """Convert a device float to the value the Core's screen shows.

    Args:
        param: Schema of the parameter, from the generated catalog.
        normalized: The raw 0.0-1.0 value read from ``object-properties``.

    Returns:
        The value in the parameter's display unit.
    """
    low, high = _bounds(param)
    algo = param.normalize_algo or LINEAR
    return _af(algo, normalized, low, high)


def to_normalized(param: ParamSchema, display: float) -> float:
    """Convert a display-unit value to the float the device expects.

    Args:
        param: Schema of the parameter, from the generated catalog.
        display: Value in the parameter's own unit (dB, ms, Hz, %, …).

    Returns:
        The 0.0-1.0 value to PUT, float32-rounded exactly as the device UI does.

    Raises:
        ParamError: The parameter is read-only, uses the broken ``DelayRatio``
            curve, or the value falls outside its declared range.
    """
    if param.read_only:
        raise ParamError(f"{param.name} is read-only")
    algo = param.normalize_algo or LINEAR
    if algo == DELAY_RATIO:
        raise ParamError(
            f"{param.name} uses normalizeAlgo 3 (DelayRatio), which has no "
            "denormalization entry in the device's own editor — refusing to guess"
        )
    low, high = _bounds(param)
    if not (low - 1e-9 <= display <= high + 1e-9):
        raise ParamError(
            f"{param.name}: {display} is outside [{low}, {high}] "
            f"{param.unit_format or ''}".strip()
        )
    return fround(_clamp(_xf(algo, display, low, high), 0.0, 1.0))


def round_trip_error(param: ParamSchema, display: float) -> float:
    """Return the display-unit error of a ``display -> normalized -> display`` cycle.

    This is the closed-loop check a writer runs after a PUT: convert, write, read
    back, convert again, and assert the error is within one ``grid`` step. It
    catches a wrong curve mechanically, without anyone having to listen.
    """
    return abs(to_display(param, to_normalized(param, display)) - display)


def within_grid(param: ParamSchema, error: float) -> bool:
    """Return True when ``error`` is within one step of the parameter's grid."""
    step = param.grid if param.grid else None
    if step is None:
        low, high = _bounds(param)
        step = abs(high - low) * 1e-3
    return error <= step * 1.5


def format_display(param: ParamSchema, display: float) -> str:
    """Render a display value the way the device's screen would.

    ``unit_format`` is a printf pattern straight from the device (``"%.0f %%"``,
    ``"%.1f dB"``, ``"%.0f ms"``), which Python's ``%`` operator accepts as-is.
    """
    if not param.unit_format:
        return f"{display:g}"
    try:
        return param.unit_format % display
    except (TypeError, ValueError):
        return f"{display:g}"


def enum_index(param: ParamSchema, label: str) -> int:
    """Resolve an enumeration label to the integer the device stores.

    Sheets store the label (``"4x12 Green 25W"``) rather than the index, because a
    firmware update can renumber options while names stay meaningful — and a wrong
    name raises here, whereas a stale index would silently select another cab.

    Raises:
        ParamError: ``label`` is not one of this parameter's options.
    """
    if not param.options:
        raise ParamError(f"{param.name} is not an enumerated parameter")
    try:
        return param.options.index(label)
    except ValueError:
        raise ParamError(
            f"{param.name}: {label!r} is not a valid option. Valid: {', '.join(param.options)}"
        ) from None


def enum_label(param: ParamSchema, index: int) -> str:
    """Return the label for an enumeration index.

    Raises:
        ParamError: The index is outside the option list.
    """
    if not param.options:
        raise ParamError(f"{param.name} is not an enumerated parameter")
    if not 0 <= index < len(param.options):
        raise ParamError(f"{param.name}: index {index} outside 0..{len(param.options) - 1}")
    return param.options[index]


def device_value(param: ParamSchema, value: Any) -> Any:
    """Convert a sheet-level value into what a PUT body should carry.

    Accepts a label for an enumerated parameter, a bool for a switch, and a
    display-unit number for a continuous one.

    Raises:
        ParamError: The value does not fit the parameter's type.
    """
    if param.type == "boolean":
        if not isinstance(value, bool):
            raise ParamError(f"{param.name} expects a boolean, got {value!r}")
        return value
    if param.options:
        if isinstance(value, str):
            return enum_index(param, value)
        if isinstance(value, int) and not isinstance(value, bool):
            enum_label(param, value)  # validate range
            return value
        raise ParamError(f"{param.name} expects one of its option labels, got {value!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParamError(f"{param.name} expects a number, got {value!r}")
    return to_normalized(param, float(value))
