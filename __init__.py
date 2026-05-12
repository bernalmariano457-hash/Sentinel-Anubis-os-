import sys as _sys
from pathlib import Path

__version__ = "2.2"
__author__ = "AnubisOS"
__all__ = [
    "RFScanner",
    "DSPEngine",
    "SDRManager",
    "MockSDRManager",
    "load_config",
    "setup_logging",
    "RFDatabase",
    "Demodulator",
]

# Añadir el directorio padre al path para que los módulos planos sean importables
_parent = str(Path(__file__).resolve().parent.parent)
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)
