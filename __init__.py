import sys as _sys
from pathlib import Path

__version__ = "2.3"
__author__ = "AnubisOS"
__all__ = [
    "DSPEngine",
    "Demodulator",
    "MockSDRManager",
    "RFDatabase",
    "RFScanner",
    "SDRManager",
    "load_config",
    "setup_logging",
]

_parent = str(Path(__file__).resolve().parent.parent)
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)
