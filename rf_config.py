"""
rf_config.py — Gestión de configuración para RFScanner.

Carga config.toml con validación de tipos y rangos.
Si el archivo no existe lo crea con valores por defecto.
Soporta override por variables de entorno: RF_GAIN_DB, RF_PPM, etc.
"""

import os
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── tomllib disponible en Python 3.11+, fallback a tomli ────────────
try:
    import tomllib  # Python 3.11+
    def _load_toml(path: Path) -> dict:
        with open(path, "rb") as f:
            return tomllib.load(f)
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli
        def _load_toml(path: Path) -> dict:
            with open(path, "rb") as f:
                return tomllib.load(f)
    except ImportError:
        # Fallback manual mínimo — solo soporta key = value simple
        def _load_toml(path: Path) -> dict:
            log.warning("tomllib/tomli no disponible — usando parser mínimo")
            result: dict = {}
            section: dict = result
            section_name = ""
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#")[0].strip()
                    if not line:
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        section_name = line[1:-1]
                        result.setdefault(section_name, {})
                        section = result[section_name]
                    elif "=" in line:
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if v.lower() == "true":   v = True
                        elif v.lower() == "false": v = False
                        else:
                            try:   v = int(v)
                            except ValueError:
                                try: v = float(v)
                                except ValueError: pass
                        section[k] = v
            return result


# ════════════════════════════════════════════════════════════════════
# DATACLASSES DE CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════════

@dataclass
class HardwareConfig:
    device_index:   int   = 0
    ppm_correction: int   = 0
    gain_db:        float = 40.0
    sample_rate:    int   = 2_048_000
    bias_tee:       bool  = False

    def validate(self):
        assert 0 <= self.device_index <= 7,         "device_index fuera de rango"
        assert -200 <= self.ppm_correction <= 200,  "ppm_correction fuera de rango"
        assert 0.0 <= self.gain_db <= 80.0,         "gain_db fuera de rango"
        assert self.sample_rate in (
            250_000, 1_024_000, 1_536_000, 1_792_000,
            1_920_000, 2_048_000, 2_160_000, 2_560_000,
            2_880_000, 3_200_000
        ), f"sample_rate no soportado: {self.sample_rate}"


@dataclass
class DspConfig:
    fft_size:        int   = 2048
    window:          str   = "blackman"
    snr_threshold:   float = 8.0
    samples_per_read: int  = 524_288
    cfar_guard:      int   = 4
    cfar_ref:        int   = 16
    dc_spike_remove: bool  = True

    def validate(self):
        assert self.fft_size in (256, 512, 1024, 2048, 4096, 8192), \
            f"fft_size debe ser potencia de 2: {self.fft_size}"
        assert self.window in ("blackman", "hann", "hamming", "flattop"), \
            f"window no reconocida: {self.window}"
        assert 0 < self.snr_threshold < 60, "snr_threshold fuera de rango"


@dataclass
class DemodConfig:
    mode:       str   = "none"
    audio_rate: int   = 48_000
    volume:     float = 0.8
    save_audio: bool  = False

    def validate(self):
        assert self.mode in ("none", "wfm", "nfm", "am", "usb", "lsb"), \
            f"modo demodulación desconocido: {self.mode}"
        assert 0.0 <= self.volume <= 1.0, "volume debe estar entre 0 y 1"


@dataclass
class StorageConfig:
    data_dir:           str = "data/rf"
    db_retention_days:  int = 0
    compress_iq:        bool = False

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

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


@dataclass
class LoggingConfig:
    level:        str = "INFO"
    file:         str = "data/rf/rfscanner.log"
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


# ════════════════════════════════════════════════════════════════════
# CARGADOR
# ════════════════════════════════════════════════════════════════════

_DEFAULT_CONFIG_CONTENT = Path(__file__).parent / "config.toml"

def load_config(path: Optional[str] = None) -> RFConfig:
    """
    Carga la configuración desde un archivo TOML.
    Precedencia: archivo → variables de entorno → defaults.
    """
    cfg_path = Path(path) if path else _find_config()

    raw: dict = {}
    if cfg_path and cfg_path.exists():
        try:
            raw = _load_toml(cfg_path)
            log.debug(f"Configuración cargada desde {cfg_path}")
        except Exception as e:
            log.warning(f"Error leyendo {cfg_path}: {e} — usando defaults")
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
    )
    dsp = DspConfig(
        fft_size         = int(_get("dsp", "fft_size",         2048)),
        window           = str(_get("dsp", "window",           "blackman")),
        snr_threshold    = float(_get("dsp", "snr_threshold",  8.0)),
        samples_per_read = int(_get("dsp", "samples_per_read", 524_288)),
        cfar_guard       = int(_get("dsp", "cfar_guard",       4)),
        cfar_ref         = int(_get("dsp", "cfar_ref",         16)),
        dc_spike_remove  = bool(_get("dsp", "dc_spike_remove", True)),
    )
    demod = DemodConfig(
        mode       = str(_get("demod", "mode",       "none")),
        audio_rate = int(_get("demod", "audio_rate", 48_000)),
        volume     = float(_get("demod", "volume",   0.8)),
        save_audio = bool(_get("demod", "save_audio", False)),
    )
    storage = StorageConfig(
        data_dir          = str(_get("storage", "data_dir",          "data/rf")),
        db_retention_days = int(_get("storage", "db_retention_days", 0)),
        compress_iq       = bool(_get("storage", "compress_iq",      False)),
    )
    display = DisplayConfig(
        waterfall_rows  = int(_get("display", "waterfall_rows",  16)),
        spectrum_width  = int(_get("display", "spectrum_width",  64)),
        spectrum_height = int(_get("display", "spectrum_height", 14)),
        dbm_floor       = float(_get("display", "dbm_floor",     -110.0)),
        dbm_ceil        = float(_get("display", "dbm_ceil",      -10.0)),
    )
    logging_cfg = LoggingConfig(
        level        = str(_get("logging", "level",        "INFO")),
        file         = str(_get("logging", "file",         "data/rf/rfscanner.log")),
        max_mb       = int(_get("logging", "max_mb",       10)),
        backup_count = int(_get("logging", "backup_count", 3)),
    )

    # ── Overrides por variables de entorno ───────────────────────────
    if (v := os.environ.get("RF_GAIN_DB")):    hw.gain_db        = float(v)
    if (v := os.environ.get("RF_PPM")):        hw.ppm_correction = int(v)
    if (v := os.environ.get("RF_DEVICE")):     hw.device_index   = int(v)
    if (v := os.environ.get("RF_SAMPLE_RATE")): hw.sample_rate   = int(v)
    if (v := os.environ.get("RF_DATA_DIR")):   storage.data_dir  = v

    cfg = RFConfig(
        hardware=hw, dsp=dsp, demod=demod,
        storage=storage, display=display, logging=logging_cfg,
    )

    # Validar rangos
    try:
        hw.validate()
        dsp.validate()
        demod.validate()
    except AssertionError as e:
        log.error(f"Configuración inválida: {e}")
        raise

    # Crear directorios necesarios
    Path(storage.data_dir).mkdir(parents=True, exist_ok=True)

    return cfg


def _find_config() -> Optional[Path]:
    """Busca config.toml en ubicaciones estándar."""
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
    """Guarda la configuración actual en TOML (sin comentarios)."""
    lines = []
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
    log.info(f"Configuración guardada en {path}")
