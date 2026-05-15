from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


_RICH_OK = False
try:
    from rich.logging import RichHandler
    _RICH_OK = True
except ImportError:
    pass

_ROOT_LOGGER = "rfscanner"


def setup_logger(
    level:        str = "INFO",
    log_file:     str | None = None,
    max_bytes:    int = 5_242_880,
    backup_count: int = 3,
    rich:         bool = True,
) -> logging.Logger:
    """
    Configura y retorna el logger raíz de rfscanner.
    Llamar una sola vez al inicio del programa.
    """
    root = logging.getLogger(_ROOT_LOGGER)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Evitar duplicar handlers si se llama varias veces
    if root.handlers:
        root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Consola ──────────────────────────────────────────────────────
    if rich and _RICH_OK:
        console_h = RichHandler(
            level=getattr(logging, level.upper(), logging.INFO),
            show_path=False,
            markup=True,
        )
    else:
        console_h = logging.StreamHandler(sys.stderr)
        console_h.setFormatter(fmt)

    root.addHandler(console_h)

    # ── Archivo con rotación ─────────────────────────────────────────
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_h = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_h.setFormatter(fmt)
            root.addHandler(file_h)
        except (OSError, PermissionError) as e:
            root.warning(f"No se puede escribir log en {log_file}: {e}")

    root.debug(f"Logger configurado — nivel {level}")
    return root


def get_logger(name: str) -> logging.Logger:
    """Retorna un logger hijo del logger raíz de rfscanner."""
    if not name.startswith(_ROOT_LOGGER):
        name = f"{_ROOT_LOGGER}.{name}"
    return logging.getLogger(name)


# Logger por defecto para módulos que importen antes de setup_logger()
_default = logging.getLogger(_ROOT_LOGGER)
if not _default.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter(
        "[%(levelname)s] %(name)s — %(message)s"))
    _default.addHandler(_h)
    _default.setLevel(logging.WARNING)
