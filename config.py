"""
rfscanner/config.py — Gestión de configuración persistente.

Búsqueda de config en orden:
  1. Ruta explícita pasada al constructor
  2. ~/.config/rfscanner/config.toml
  3. ./config.toml (directorio de trabajo)
  4. Defaults internos (sin archivo)

Uso:
    from rfscanner.config import Config
    cfg = Config()           # busca automáticamente
    cfg = Config("/ruta/mi_config.toml")
    print(cfg.hardware.gain)
    cfg.hardware.gain = 35.0
    cfg.save()
"""

import os
import copy
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Intentar importar tomllib (Python ≥ 3.11) o tomli (pip) ────────
try:
    import tomllib                      # stdlib Python 3.11+
    _TOML_READ = tomllib
    _TOML_WRITE = None
except ImportError:
    try:
        import tomli as _TOML_READ      # pip install tomli
        _TOML_WRITE = None
    except ImportError:
        _TOML_READ = None
        _TOML_WRITE = None

try:
    import tomli_w as _TOML_WRITE       # pip install tomli-w
except ImportError:
    pass


# ════════════════════════════════════════════════════════════════════
# DATACLASSES DE CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════════

@dataclass
class HardwareConfig:
    device_index:        int   = 0
    gain:                float = 40.0
    ppm_correction:      int   = 0
    sample_rate:         int   = 2_048_000
    reconnect_timeout:   float = 5.0
    reconnect_attempts:  int   = 3


@dataclass
class DspConfig:
    fft_size:          int   = 2048
    window:            str   = "blackman"
    snr_threshold:     float = 8.0
    samples_per_read:  int   = 524_288
    waterfall_rows:    int   = 16
    remove_dc_spike:   bool  = True


@dataclass
class DemodConfig:
    mode:         str   = "nfm"
    audio_rate:   int   = 48_000
    audio_device: int   = -1
    volume:       float = 0.8
    squelch_db:   float = 5.0


@dataclass
class StorageConfig:
    evidence_dir:  str  = "data/evidence/rf"
    iq_dir:        str  = "data/evidence/rf/iq"
    db_path:       str  = "data/evidence/rf/signals.db"
    sigmf_format:  bool = True
    session_max:   int  = 10_000


@dataclass
class UiConfig:
    spectrum_width:  int  = 64
    spectrum_height: int  = 14
    display_every:   int  = 1
    clear_screen:    bool = True


@dataclass
class LoggingConfig:
    level:        str = "INFO"
    file:         str = "data/logs/rfscanner.log"
    max_bytes:    int = 5_242_880
    backup_count: int = 3


# ════════════════════════════════════════════════════════════════════
# CONFIG PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class Config:
    """
    Configuración global de RFScanner con persistencia TOML.
    Si TOML no está disponible, opera con defaults en memoria.
    """

    SEARCH_PATHS = [
        Path.home() / ".config" / "rfscanner" / "config.toml",
        Path("config.toml"),
        Path(__file__).parent.parent / "config_default.toml",
    ]

    def __init__(self, path: Optional[str] = None):
        self.hardware = HardwareConfig()
        self.dsp      = DspConfig()
        self.demod    = DemodConfig()
        self.storage  = StorageConfig()
        self.ui       = UiConfig()
        self.logging  = LoggingConfig()
        self._path: Optional[Path] = None

        if path:
            self._path = Path(path)
            self._load(self._path)
        else:
            for candidate in self.SEARCH_PATHS:
                if candidate.exists():
                    self._path = candidate
                    self._load(candidate)
                    break
            else:
                log.info("Config: sin archivo encontrado, usando defaults")

    # ── Carga ───────────────────────────────────────────────────────

    def _load(self, path: Path):
        if _TOML_READ is None:
            log.warning("tomllib/tomli no disponible — install: pip install tomli tomli-w")
            return
        try:
            raw = path.read_bytes()
            data = _TOML_READ.loads(raw.decode()) if hasattr(_TOML_READ, 'loads') else _TOML_READ.load(
                __import__('io').BytesIO(raw)
            )
            self._apply(data)
            log.info(f"Config cargada: {path}")
        except Exception as e:
            log.error(f"Error leyendo config {path}: {e}")

    def _apply(self, data: dict):
        """Aplica un dict TOML sobre los dataclasses, ignorando claves desconocidas."""
        def merge(dc, section: dict):
            for k, v in section.items():
                if hasattr(dc, k):
                    setattr(dc, k, v)
        if "hardware" in data: merge(self.hardware, data["hardware"])
        if "dsp"      in data: merge(self.dsp,      data["dsp"])
        if "demod"    in data: merge(self.demod,     data["demod"])
        if "storage"  in data: merge(self.storage,   data["storage"])
        if "ui"       in data: merge(self.ui,        data["ui"])
        if "logging"  in data: merge(self.logging,   data["logging"])

    # ── Guardado ────────────────────────────────────────────────────

    def save(self, path: Optional[str] = None):
        """Guarda la configuración actual en TOML."""
        target = Path(path) if path else self._path
        if target is None:
            target = Path.home() / ".config" / "rfscanner" / "config.toml"
        target.parent.mkdir(parents=True, exist_ok=True)

        if _TOML_WRITE is None:
            # Fallback: escritura manual básica
            self._save_manual(target)
            return

        data = {
            "hardware": asdict(self.hardware),
            "dsp":      asdict(self.dsp),
            "demod":    asdict(self.demod),
            "storage":  asdict(self.storage),
            "ui":       asdict(self.ui),
            "logging":  asdict(self.logging),
        }
        try:
            with open(target, "wb") as f:
                _TOML_WRITE.dump(data, f)
            log.info(f"Config guardada: {target}")
            self._path = target
        except Exception as e:
            log.error(f"Error guardando config: {e}")

    def _save_manual(self, target: Path):
        """Escritura TOML manual sin dependencias (solo tipos básicos)."""
        lines = []
        def section(name, dc):
            lines.append(f"\n[{name}]")
            for k, v in asdict(dc).items():
                if isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                else:
                    lines.append(f"{k} = {v}")

        section("hardware", self.hardware)
        section("dsp",      self.dsp)
        section("demod",    self.demod)
        section("storage",  self.storage)
        section("ui",       self.ui)
        section("logging",  self.logging)

        try:
            target.write_text("\n".join(lines), encoding="utf-8")
            log.info(f"Config guardada (manual): {target}")
        except Exception as e:
            log.error(f"Error guardando config manual: {e}")

    def update_ppm(self, ppm: int):
        """Actualiza corrección PPM y persiste."""
        self.hardware.ppm_correction = ppm
        self.save()

    def update_gain(self, gain: float):
        """Actualiza ganancia y persiste."""
        self.hardware.gain = gain
        self.save()

    def __repr__(self):
        return (f"Config(path={self._path}, "
                f"gain={self.hardware.gain}, "
                f"sr={self.hardware.sample_rate/1e6:.3f}MHz, "
                f"fft={self.dsp.fft_size})")
