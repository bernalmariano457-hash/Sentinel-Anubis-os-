from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.platform import Platform, PlatformInfo, detect as detect_platform

_CONFIG_PATH = Path("config/keybindings.toml")

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        tomllib = None


@dataclass
class BandPreset:
    freq_mhz: float
    span_mhz: float
    label:    str


@dataclass
class KeyBindings:

    tune_right:    list[str] = field(default_factory=lambda: ["RIGHT", "d"])
    tune_left:     list[str] = field(default_factory=lambda: ["LEFT",  "a"])

    span_up:       list[str] = field(default_factory=lambda: ["+", "="])
    span_down:     list[str] = field(default_factory=lambda: ["-"])

    ref_up:        list[str] = field(default_factory=lambda: ["UP",   "w"])
    ref_down:      list[str] = field(default_factory=lambda: ["DOWN", "s"])

    toggle_peak:   list[str] = field(default_factory=lambda: ["p"])
    toggle_avg:    list[str] = field(default_factory=lambda: ["v"])
    clear_buffer:  list[str] = field(default_factory=lambda: ["c"])

    marker_1:      list[str] = field(default_factory=lambda: ["m"])
    marker_2:      list[str] = field(default_factory=lambda: ["n"])

    cycle_gain:    list[str] = field(default_factory=lambda: ["g"])
    export_frame:  list[str] = field(default_factory=lambda: ["e"])
    quit:          list[str] = field(default_factory=lambda: [
                                     "q", "Q", "ESC", "\x03"])

    bands:         dict[str, BandPreset] = field(default_factory=dict)

    display_cols:  int = 0
    display_rows:  int = 0

    def key_to_action(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for action in (
            "tune_right", "tune_left", "span_up", "span_down",
            "ref_up", "ref_down", "toggle_peak", "toggle_avg",
            "clear_buffer", "marker_1", "marker_2",
            "cycle_gain", "export_frame", "quit",
        ):
            for key in getattr(self, action):
                mapping[key] = action

        for fname, preset in self.bands.items():
            mapping[fname] = f"band:{fname}"
        return mapping


_DEFAULT_BANDS: dict[str, BandPreset] = {
    "F1":  BandPreset(88.0,    20.0, "FM Broadcast"),
    "F2":  BandPreset(137.5,   3.0,  "NOAA Weather Sat"),
    "F3":  BandPreset(144.0,   6.0,  "VHF Amateur"),
    "F4":  BandPreset(433.920, 2.0,  "ISM 433 MHz"),
    "F5":  BandPreset(462.5,   5.0,  "GMRS / FRS"),
    "F6":  BandPreset(868.0,   4.0,  "ISM 868 MHz"),
    "F7":  BandPreset(915.0,   4.0,  "ISM 915 MHz"),
    "F8":  BandPreset(1090.0,  4.0,  "ADS-B Mode S"),
    "F9":  BandPreset(1575.42, 4.0,  "GPS L1"),
    "F10": BandPreset(433.920, 0.5,  "ISM 433 Zoom"),
}

_TERMUX_BAND_ALIASES: dict[str, str] = {
    "1": "F1", "2": "F2", "3": "F3", "4": "F4", "5": "F5",
}


def load(info: PlatformInfo | None = None) -> KeyBindings:
    info = info or detect_platform()
    raw = _read_toml()
    kb = KeyBindings()

    _apply_section(kb, raw.get("global", {}))

    section_name = {
        Platform.UCONSOLE: "uconsole",
        Platform.TERMUX:   "termux",
        Platform.KALI:     "kali",
        Platform.RASPI:    "kali",
        Platform.GENERIC:  "kali",
    }.get(info.kind, "kali")
    _apply_section(kb, raw.get(section_name, {}))

    bands_raw = raw.get("bands", {})
    kb.bands = _DEFAULT_BANDS.copy()
    for key, val in bands_raw.items():
        if isinstance(val, dict):
            kb.bands[key] = BandPreset(
                freq_mhz=float(val.get("freq_mhz", 433.920)),
                span_mhz=float(val.get("span_mhz", 2.0)),
                label=str(val.get("label", key)),
            )

    if info.is_termux:
        termux_raw = raw.get("termux", {})
        alias_map = {
            "band_fm":    "F1", "band_noaa": "F2",
            "band_ism433": "F4", "band_ism915": "F7", "band_adsb": "F8",
        }
        for cfg_key, f_key in alias_map.items():
            if cfg_key in termux_raw:
                keys = termux_raw[cfg_key]
                if isinstance(keys, list):
                    for k in keys:
                        kb.bands[k] = kb.bands.get(
                            f_key, BandPreset(433.920, 2.0, f_key))

    return kb


def _read_toml() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    if tomllib is None:
        return {}
    try:
        with _CONFIG_PATH.open("rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


def _apply_section(kb: KeyBindings, section: dict[str, Any]) -> None:
    str_list_fields = {
        "tune_right", "tune_left", "span_up", "span_down",
        "ref_up", "ref_down", "toggle_peak", "toggle_avg",
        "clear_buffer", "marker_1", "marker_2",
        "cycle_gain", "export_frame", "quit",
    }
    for key, val in section.items():
        if key in str_list_fields and isinstance(val, list):
            setattr(kb, key, [str(v) for v in val])
        elif key == "display_cols" and isinstance(val, int):
            kb.display_cols = val
        elif key == "display_rows" and isinstance(val, int):
            kb.display_rows = val
