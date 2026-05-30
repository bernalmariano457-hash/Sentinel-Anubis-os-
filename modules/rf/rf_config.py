from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger(__name__)

try:
    import tomllib

    def _load_toml(path: Path) -> dict:
        with open(path, "rb") as f:
            return tomllib.load(f)

except ImportError:
    try:
        import tomli as tomllib  # type: ignore

        def _load_toml(path: Path) -> dict:
            with open(path, "rb") as f:
                return tomllib.load(f)

    except ImportError:

        def _load_toml(path: Path) -> dict:  # type: ignore
            log.warning("tomllib/tomli no disponible — parser minimo activo")
            result: dict = {}
            section: dict = result
            with open(path, encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.split("#")[0].strip()
                    if not line:
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        key = line[1:-1]
                        result.setdefault(key, {})
                        section = result[key]
                    elif "=" in line:
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if v.lower() == "true":
                            v = True
                        elif v.lower() == "false":
                            v = False
                        else:
                            try:
                                v = int(v)
                            except ValueError:
                                try:
                                    v = float(v)
                                except ValueError:
                                    pass
                        section[k] = v
            return result

# DATACLASSES DE CONFIGURACION

_VALID_SAMPLE_RATES = frozenset({
    250_000, 1_024_000, 1_536_000, 1_792_000,
    1_920_000, 2_048_000, 2_160_000, 2_560_000,
    2_880_000, 3_200_000,
})

_VALID_WINDOWS = frozenset({"blackman", "hann", "hamming", "flattop"})
_VALID_MODES   = frozenset({"none", "wfm", "nfm", "am", "usb", "lsb"})
_VALID_FFT     = frozenset({256, 512, 1024, 2048, 4096, 8192})

@dataclass
class HardwareConfig:
    device_index:   int   = 0
    ppm_correction: int   = 0
    gain_db:        float = 40.0
    sample_rate:    int   = 2_048_000
    bias_tee:       bool  = False
    agc:            bool  = False

    def validate(self) -> None:
        if not (0 <= self.device_index <= 7):
            raise ValueError(f"device_index fuera de rango: {self.device_index}")
        if not (-200 <= self.ppm_correction <= 200):
            raise ValueError(f"ppm_correction fuera de rango: {self.ppm_correction}")
        if not (0.0 <= self.gain_db <= 80.0):
            raise ValueError(f"gain_db fuera de rango: {self.gain_db}")
        if self.sample_rate not in _VALID_SAMPLE_RATES:
            raise ValueError(f"sample_rate no soportado: {self.sample_rate}")

@dataclass
class DspConfig:
    fft_size:         int   = 2048
    window:           str   = "blackman"
    snr_threshold:    float = 8.0
    samples_per_read: int   = 524_288
    cfar_guard:       int   = 4
    cfar_ref:         int   = 16
    dc_spike_remove:  bool  = True
    welch_overlap:    float = 0.5

    def validate(self) -> None:
        if self.fft_size not in _VALID_FFT:
            raise ValueError(f"fft_size debe ser potencia de 2: {self.fft_size}")
        if self.window not in _VALID_WINDOWS:
            raise ValueError(f"window no reconocida: {self.window}")
        if not (0 < self.snr_threshold < 60):
            raise ValueError("snr_threshold fuera de rango [0, 60]")
        if not (0.0 <= self.welch_overlap < 1.0):
            raise ValueError("welch_overlap debe estar en [0, 1)")

@dataclass
class DemodConfig:
    mode:       str   = "none"
    audio_rate: int   = 48_000
    volume:     float = 0.8
    save_audio: bool  = False
    squelch_db: float = 0.0

    def validate(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(f"modo demodulacion desconocido: {self.mode}")
        if not (0.0 <= self.volume <= 1.0):
            raise ValueError("volume debe estar entre 0 y 1")

@dataclass
class StorageConfig:
    data_dir:          Path = field(default_factory=lambda: Path("data/rf"))
    db_retention_days: int  = 0
    compress_iq:       bool = False
    sigmf_format:      bool = True

    @property
    def data_path(self) -> Path:
        return self.data_dir

    @property
    def db_path(self) -> Path:
        return self.data_path / "signals.db"

    @property
    def iq_path(self) -> Path:
        p = self.data_path / "iq"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def csv_path(self) -> Path:
        p = self.data_path / "csv"
        p.mkdir(parents=True, exist_ok=True)
        return p

@dataclass
class DisplayConfig:
    waterfall_rows:  int   = 16
    spectrum_width:  int   = 64
    spectrum_height: int   = 14
    dbm_floor:       float = -110.0
    dbm_ceil:        float = -10.0
    color_scheme:    str   = "default"

@dataclass
class LoggingConfig:
    level:        str = "INFO"
    file:         Path = field(default_factory=lambda: Path("data/rf/rfscanner.log"))
    max_mb:       int = 10
    backup_count: int = 3

@dataclass
class RFConfig:
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    dsp:      DspConfig      = field(default_factory=DspConfig)
    demod:    DemodConfig    = field(default_factory=DemodConfig)
    storage:  StorageConfig  = field(default_factory=StorageConfig)
    display:  DisplayConfig  = field(default_factory=DisplayConfig)
    logging:  LoggingConfig  = field(default_factory=LoggingConfig)

# CARGADOR

def load_config(path: str | None = None) -> RFConfig:
    cfg_path = Path(path) if path else _find_config()

    raw: dict = {}
    if cfg_path and cfg_path.exists():
        try:
            raw = _load_toml(cfg_path)
            log.debug("Configuracion cargada desde %s", cfg_path)
        except Exception as e:
            log.warning("Error leyendo %s: %s — usando defaults", cfg_path, e)
    else:
        log.info("config.toml no encontrado — usando valores por defecto")

    def _get(section: str, key: str, default):
        return raw.get(section, {}).get(key, default)

    hw = HardwareConfig(
        device_index   = int(_get("hardware", "device_index",   0)),
        ppm_correction = int(_get("hardware", "ppm_correction", 0)),
        gain_db        = float(_get("hardware", "gain_db",      40.0)),
        sample_rate    = int(_get("hardware", "sample_rate",    2_048_000)),
        bias_tee       = bool(_get("hardware", "bias_tee",      False)),
        agc            = bool(_get("hardware", "agc",           False)),
    )
    dsp = DspConfig(
        fft_size         = int(_get("dsp", "fft_size",         2048)),
        window           = str(_get("dsp", "window",           "blackman")),
        snr_threshold    = float(_get("dsp", "snr_threshold",  8.0)),
        samples_per_read = int(_get("dsp", "samples_per_read", 524_288)),
        cfar_guard       = int(_get("dsp", "cfar_guard",       4)),
        cfar_ref         = int(_get("dsp", "cfar_ref",         16)),
        dc_spike_remove  = bool(_get("dsp", "dc_spike_remove", True)),
        welch_overlap    = float(_get("dsp", "welch_overlap",  0.5)),
    )
    demod = DemodConfig(
        mode       = str(_get("demod", "mode",       "none")),
        audio_rate = int(_get("demod", "audio_rate", 48_000)),
        volume     = float(_get("demod", "volume",   0.8)),
        save_audio = bool(_get("demod", "save_audio", False)),
        squelch_db = float(_get("demod", "squelch_db", 0.0)),
    )
    storage = StorageConfig(
        data_dir          = Path(_get("storage", "data_dir",         "data/rf")),
        db_retention_days = int(_get("storage", "db_retention_days", 0)),
        compress_iq       = bool(_get("storage", "compress_iq",      False)),
        sigmf_format      = bool(_get("storage", "sigmf_format",     True)),
    )
    display = DisplayConfig(
        waterfall_rows  = int(_get("display", "waterfall_rows",  16)),
        spectrum_width  = int(_get("display", "spectrum_width",  64)),
        spectrum_height = int(_get("display", "spectrum_height", 14)),
        dbm_floor       = float(_get("display", "dbm_floor",     -110.0)),
        dbm_ceil        = float(_get("display", "dbm_ceil",      -10.0)),
        color_scheme    = str(_get("display", "color_scheme",    "default")),
    )
    logging_cfg = LoggingConfig(
        level        = str(_get("logging", "level",        "INFO")),
        file         = Path(_get("logging", "file",        "data/rf/rfscanner.log")),
        max_mb       = int(_get("logging", "max_mb",       10)),
        backup_count = int(_get("logging", "backup_count", 3)),
    )

    # Overrides por variable de entorno (mayor prioridad que TOML)
    _env_overrides = {
        "RF_GAIN_DB":    ("hw.gain_db",         float),
        "RF_PPM":        ("hw.ppm_correction",  int),
        "RF_DEVICE":     ("hw.device_index",    int),
        "RF_SAMPLE_RATE":("hw.sample_rate",     int),
        "RF_DATA_DIR":   ("storage.data_dir",   str),
        "RF_SNR_THRESH": ("dsp.snr_threshold",  float),
        "RF_DEMOD_MODE": ("demod.mode",         str),
    }
    for env_var, (target, cast) in _env_overrides.items():
        if v := os.environ.get(env_var):
            obj_name, attr = target.split(".")
            obj = {"hw": hw, "dsp": dsp, "demod": demod, "storage": storage}[obj_name]
            try:
                setattr(obj, attr, cast(v))
                log.debug("Override: %s=%s (via %s)", attr, v, env_var)
            except Exception as e:
                log.warning("Override invalido %s=%s: %s", env_var, v, e)

    cfg = RFConfig(
        hardware=hw, dsp=dsp, demod=demod,
        storage=storage, display=display, logging=logging_cfg,
    )

    try:
        hw.validate()
        dsp.validate()
        demod.validate()
    except ValueError as e:
        log.error("Configuracion invalida: %s", e)
        raise

    Path(storage.data_dir).mkdir(parents=True, exist_ok=True)
    return cfg

def _find_config() -> Path | None:
    candidates = [
        Path("config.toml"),
        Path("rfscanner/config.toml"),
        Path.home() / ".config" / "rfscanner" / "config.toml",
        Path(__file__).parent / "config.toml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def save_config(cfg: RFConfig, path: str = "config.toml"):
    lines: list[str] = []
    for section_name, section_obj in asdict(cfg).items():
        lines.append(f"\n[{section_name}]")
        for k, v in section_obj.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
            else:
                lines.append(f"{k} = {v}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Configuracion guardada en %s", path)
