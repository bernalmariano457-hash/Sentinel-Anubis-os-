from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Final, TypeVar

log: Final = logging.getLogger("sentinel.rf.config")

_T = TypeVar("_T")

_VALID_SAMPLE_RATES_HZ: Final[frozenset[int]] = frozenset({
    250_000,
    1_024_000,
    1_536_000,
    1_792_000,
    1_920_000,
    2_048_000,
    2_160_000,
    2_560_000,
    2_880_000,
    3_200_000,
})

_VALID_FFT_SIZES: Final[frozenset[int]] = frozenset({256, 512, 1_024, 2_048, 4_096, 8_192})

_VALID_DSP_WINDOWS: Final[frozenset[str]] = frozenset({
    "blackman", "hann", "hamming", "flattop", "kaiser", "nuttall",
})

_VALID_DEMOD_MODES: Final[frozenset[str]] = frozenset({
    "none", "wfm", "nfm", "am", "usb", "lsb", "cw", "raw",
})

_CONFIG_SEARCH_PATHS: Final[tuple[Path, ...]] = (
    Path("config.toml"),
    Path("rfscanner/config.toml"),
    Path.home() / ".config" / "rfscanner" / "config.toml",
    Path(__file__).parent / "config.toml",
)

_ENV_OVERRIDE_MAP: Final[tuple[tuple[str, str, str, type], ...]] = (
    ("RF_GAIN_DB",     "hardware", "gain_db",        float),
    ("RF_PPM",         "hardware", "ppm_correction", int),
    ("RF_DEVICE",      "hardware", "device_index",   int),
    ("RF_SAMPLE_RATE", "hardware", "sample_rate",    int),
    ("RF_DATA_DIR",    "storage",  "data_dir",       str),
    ("RF_SNR_THRESH",  "dsp",      "snr_threshold",  float),
    ("RF_DEMOD_MODE",  "demod",    "mode",           str),
    ("RF_FFT_SIZE",    "dsp",      "fft_size",       int),
    ("RF_DSP_WINDOW",  "dsp",      "window",         str),
    ("RF_BIAS_TEE",    "hardware", "bias_tee",       lambda v: v.lower() in ("1", "true", "yes")),
)


def _resolve_toml_loader() -> Callable[[Path], dict[str, Any]]:
    try:
        import tomllib as _tomllib

        def _load_native(path: Path) -> dict[str, Any]:
            with path.open("rb") as fh:
                return _tomllib.load(fh)

        return _load_native

    except ImportError:
        pass

    try:
        import tomli as _tomli  # type: ignore

        def _load_tomli(path: Path) -> dict[str, Any]:
            with path.open("rb") as fh:
                return _tomli.load(fh)

        return _load_tomli

    except ImportError:
        pass

    def _load_minimal(path: Path) -> dict[str, Any]:
        log.warning("tomllib/tomli unavailable — using minimal TOML parser")
        result: dict[str, Any] = {}
        current_section: dict[str, Any] = result
        with path.open(encoding="utf-8") as fh:
            for raw_line in fh:
                stripped = raw_line.split("#", 1)[0].strip()
                if not stripped:
                    continue
                if stripped.startswith("[") and stripped.endswith("]"):
                    section_key = stripped[1:-1].strip()
                    result.setdefault(section_key, {})
                    current_section = result[section_key]
                elif "=" in stripped:
                    key, _, raw_value = stripped.partition("=")
                    key = key.strip()
                    raw_value = raw_value.strip().strip('"').strip("'")
                    if raw_value.lower() == "true":
                        parsed_value: Any = True
                    elif raw_value.lower() == "false":
                        parsed_value = False
                    else:
                        try:
                            parsed_value = int(raw_value)
                        except ValueError:
                            try:
                                parsed_value = float(raw_value)
                            except ValueError:
                                parsed_value = raw_value
                    current_section[key] = parsed_value
        return result

    return _load_minimal


_toml_load: Final[Callable[[Path], dict[str, Any]]] = _resolve_toml_loader()


@dataclass(slots=True)
class HardwareConfig:
    device_index: int = 0
    ppm_correction: int = 0
    gain_db: float = 40.0
    sample_rate: int = 2_048_000
    bias_tee: bool = False
    agc: bool = False

    def validate(self) -> None:
        if not (0 <= self.device_index <= 7):
            raise ValueError(f"device_index out of range [0, 7]: {self.device_index}")
        if not (-200 <= self.ppm_correction <= 200):
            raise ValueError(f"ppm_correction out of range [-200, 200]: {self.ppm_correction}")
        if not (0.0 <= self.gain_db <= 80.0):
            raise ValueError(f"gain_db out of range [0.0, 80.0]: {self.gain_db}")
        if self.sample_rate not in _VALID_SAMPLE_RATES_HZ:
            raise ValueError(
                f"sample_rate {self.sample_rate} not in supported set: "
                f"{sorted(_VALID_SAMPLE_RATES_HZ)}"
            )

    @property
    def bandwidth_hz(self) -> float:
        return float(self.sample_rate)

    @property
    def nyquist_hz(self) -> float:
        return self.sample_rate / 2.0


@dataclass(slots=True)
class DspConfig:
    fft_size: int = 2_048
    window: str = "blackman"
    snr_threshold: float = 8.0
    samples_per_read: int = 524_288
    cfar_guard_bins: int = 4
    cfar_reference_bins: int = 16
    dc_spike_remove: bool = True
    welch_overlap: float = 0.5

    def validate(self) -> None:
        if self.fft_size not in _VALID_FFT_SIZES:
            raise ValueError(
                f"fft_size must be a power of 2 in {sorted(_VALID_FFT_SIZES)}: {self.fft_size}"
            )
        if self.window not in _VALID_DSP_WINDOWS:
            raise ValueError(f"window not recognized: {self.window}. Valid: {_VALID_DSP_WINDOWS}")
        if not (0.0 < self.snr_threshold < 60.0):
            raise ValueError(f"snr_threshold out of range (0, 60): {self.snr_threshold}")
        if not (0.0 <= self.welch_overlap < 1.0):
            raise ValueError(f"welch_overlap must be in [0.0, 1.0): {self.welch_overlap}")
        if self.samples_per_read < self.fft_size:
            raise ValueError(
                f"samples_per_read ({self.samples_per_read}) must be >= fft_size ({self.fft_size})"
            )
        if self.cfar_guard_bins < 1:
            raise ValueError(f"cfar_guard_bins must be >= 1: {self.cfar_guard_bins}")
        if self.cfar_reference_bins < self.cfar_guard_bins:
            raise ValueError(
                f"cfar_reference_bins ({self.cfar_reference_bins}) "
                f"must be >= cfar_guard_bins ({self.cfar_guard_bins})"
            )

    def frequency_resolution_hz(self, sample_rate: int) -> float:
        return sample_rate / self.fft_size

    def overlap_stride(self) -> int:
        return max(1, int(self.fft_size * (1.0 - self.welch_overlap)))

    def max_welch_frames(self) -> int:
        stride = self.overlap_stride()
        return max(1, (self.samples_per_read - self.fft_size) // stride + 1)


@dataclass(slots=True)
class DemodConfig:
    mode: str = "none"
    audio_rate: int = 48_000
    volume: float = 0.8
    save_audio: bool = False
    squelch_db: float = 0.0

    def validate(self) -> None:
        if self.mode not in _VALID_DEMOD_MODES:
            raise ValueError(f"unknown demod mode: {self.mode}. Valid: {_VALID_DEMOD_MODES}")
        if not (0.0 <= self.volume <= 1.0):
            raise ValueError(f"volume must be in [0.0, 1.0]: {self.volume}")
        if not (8_000 <= self.audio_rate <= 192_000):
            raise ValueError(f"audio_rate out of range [8000, 192000]: {self.audio_rate}")

    @property
    def is_active(self) -> bool:
        return self.mode != "none"


@dataclass(slots=True)
class StorageConfig:
    data_dir: Path = field(default_factory=lambda: Path("data/rf"))
    db_retention_days: int = 0
    compress_iq: bool = False
    sigmf_format: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "signals.db"

    @property
    def iq_path(self) -> Path:
        p = self.data_dir / "iq"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def csv_path(self) -> Path:
        p = self.data_dir / "csv"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "iq").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "csv").mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class DisplayConfig:
    waterfall_rows: int = 16
    spectrum_width: int = 64
    spectrum_height: int = 14
    dbm_floor: float = -110.0
    dbm_ceil: float = -10.0
    color_scheme: str = "default"

    def validate(self) -> None:
        if self.dbm_floor >= self.dbm_ceil:
            raise ValueError(
                f"dbm_floor ({self.dbm_floor}) must be less than dbm_ceil ({self.dbm_ceil})"
            )
        if self.spectrum_width < 16:
            raise ValueError(f"spectrum_width must be >= 16: {self.spectrum_width}")
        if self.spectrum_height < 4:
            raise ValueError(f"spectrum_height must be >= 4: {self.spectrum_height}")

    @property
    def dbm_range(self) -> float:
        return self.dbm_ceil - self.dbm_floor


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    file: Path = field(default_factory=lambda: Path("data/rf/rfscanner.log"))
    max_mb: int = 10
    backup_count: int = 3

    @property
    def max_bytes(self) -> int:
        return self.max_mb * 1_048_576


@dataclass(slots=True)
class RFConfig:
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    dsp: DspConfig = field(default_factory=DspConfig)
    demod: DemodConfig = field(default_factory=DemodConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def freq_resolution_hz(self) -> float:
        return self.dsp.frequency_resolution_hz(self.hardware.sample_rate)

    def freq_resolution_khz(self) -> float:
        return self.freq_resolution_hz() / 1_000.0


def _find_config_file() -> Path | None:
    return next((p for p in _CONFIG_SEARCH_PATHS if p.exists()), None)


def _read_toml_safe(cfg_path: Path) -> dict[str, Any]:
    try:
        data = _toml_load(cfg_path)
        log.debug("Config loaded from %s", cfg_path)
        return data
    except Exception as exc:
        log.warning("Failed to read %s: %s — using defaults", cfg_path, exc)
        return {}


def _extract(raw: dict[str, Any], section: str, key: str, default: _T, cast: type | Callable) -> _T:
    raw_value = raw.get(section, {}).get(key, default)
    if raw_value is default:
        return default
    try:
        return cast(raw_value)  # type: ignore[return-value]
    except (TypeError, ValueError) as exc:
        log.warning("Config value [%s].%s=%r invalid (%s) — using default %r", section, key, raw_value, exc, default)
        return default


def _apply_env_overrides(
    hw: HardwareConfig,
    dsp: DspConfig,
    demod: DemodConfig,
    storage: StorageConfig,
) -> None:
    section_map: dict[str, Any] = {
        "hardware": hw,
        "dsp": dsp,
        "demod": demod,
        "storage": storage,
    }
    for env_var, section_name, attr_name, cast in _ENV_OVERRIDE_MAP:
        raw_env_value = os.environ.get(env_var)
        if raw_env_value is None:
            continue
        target_obj = section_map.get(section_name)
        if target_obj is None:
            continue
        try:
            setattr(target_obj, attr_name, cast(raw_env_value))
            log.debug("Env override applied: [%s].%s=%s (via %s)", section_name, attr_name, raw_env_value, env_var)
        except Exception as exc:
            log.warning("Invalid env override %s=%r: %s", env_var, raw_env_value, exc)


def load_config(path: str | None = None) -> RFConfig:
    cfg_path = Path(path) if path else _find_config_file()
    raw: dict[str, Any] = _read_toml_safe(cfg_path) if cfg_path and cfg_path.exists() else {}

    if not raw:
        log.info("No config.toml found — using built-in defaults")

    hw = HardwareConfig(
        device_index=_extract(raw, "hardware", "device_index", 0, int),
        ppm_correction=_extract(raw, "hardware", "ppm_correction", 0, int),
        gain_db=_extract(raw, "hardware", "gain_db", 40.0, float),
        sample_rate=_extract(raw, "hardware", "sample_rate", 2_048_000, int),
        bias_tee=_extract(raw, "hardware", "bias_tee", False, bool),
        agc=_extract(raw, "hardware", "agc", False, bool),
    )
    dsp = DspConfig(
        fft_size=_extract(raw, "dsp", "fft_size", 2_048, int),
        window=_extract(raw, "dsp", "window", "blackman", str),
        snr_threshold=_extract(raw, "dsp", "snr_threshold", 8.0, float),
        samples_per_read=_extract(raw, "dsp", "samples_per_read", 524_288, int),
        cfar_guard_bins=_extract(raw, "dsp", "cfar_guard", 4, int),
        cfar_reference_bins=_extract(raw, "dsp", "cfar_ref", 16, int),
        dc_spike_remove=_extract(raw, "dsp", "dc_spike_remove", True, bool),
        welch_overlap=_extract(raw, "dsp", "welch_overlap", 0.5, float),
    )
    demod = DemodConfig(
        mode=_extract(raw, "demod", "mode", "none", str),
        audio_rate=_extract(raw, "demod", "audio_rate", 48_000, int),
        volume=_extract(raw, "demod", "volume", 0.8, float),
        save_audio=_extract(raw, "demod", "save_audio", False, bool),
        squelch_db=_extract(raw, "demod", "squelch_db", 0.0, float),
    )
    storage = StorageConfig(
        data_dir=Path(_extract(raw, "storage", "data_dir", "data/rf", str)),
        db_retention_days=_extract(raw, "storage", "db_retention_days", 0, int),
        compress_iq=_extract(raw, "storage", "compress_iq", False, bool),
        sigmf_format=_extract(raw, "storage", "sigmf_format", True, bool),
    )
    display = DisplayConfig(
        waterfall_rows=_extract(raw, "display", "waterfall_rows", 16, int),
        spectrum_width=_extract(raw, "display", "spectrum_width", 64, int),
        spectrum_height=_extract(raw, "display", "spectrum_height", 14, int),
        dbm_floor=_extract(raw, "display", "dbm_floor", -110.0, float),
        dbm_ceil=_extract(raw, "display", "dbm_ceil", -10.0, float),
        color_scheme=_extract(raw, "display", "color_scheme", "default", str),
    )
    logging_cfg = LoggingConfig(
        level=_extract(raw, "logging", "level", "INFO", str),
        file=Path(_extract(raw, "logging", "file", "data/rf/rfscanner.log", str)),
        max_mb=_extract(raw, "logging", "max_mb", 10, int),
        backup_count=_extract(raw, "logging", "backup_count", 3, int),
    )

    _apply_env_overrides(hw, dsp, demod, storage)

    try:
        hw.validate()
        dsp.validate()
        demod.validate()
        display.validate()
    except ValueError as exc:
        log.error("Invalid configuration: %s", exc)
        raise

    storage.ensure_directories()

    return RFConfig(
        hardware=hw,
        dsp=dsp,
        demod=demod,
        storage=storage,
        display=display,
        logging=logging_cfg,
    )


def save_config(cfg: RFConfig, path: str | Path = "config.toml") -> None:
    output_path = Path(path)
    raw = asdict(cfg)
    lines: list[str] = []

    for section_name, section_fields in raw.items():
        lines.append(f"\n[{section_name}]")
        for field_name, field_value in section_fields.items():
            if isinstance(field_value, bool):
                lines.append(f"{field_name} = {'true' if field_value else 'false'}")
            elif isinstance(field_value, str):
                lines.append(f'{field_name} = "{field_value}"')
            elif isinstance(field_value, Path):
                lines.append(f'{field_name} = "{field_value}"')
            else:
                lines.append(f"{field_name} = {field_value}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Config saved to %s", output_path)
