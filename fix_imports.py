
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ── Mapa: nombre_módulo → carpeta donde vive ahora ───────────────
MODULO_A_PAQUETE = {
    # core
    "auth":             "core",
    "Security":         "core",
    "ColaTareas":       "core",
    "GestorProyectos":  "core",
    "bootscreen":       "core",
    "command_handler":  "core",
    "logger":           "core",
    "log_sistema":      "core",
    "log_visual":       "core",
    "PluginSystem":     "core",
    "SystemChecker":    "core",
    "Recovery":         "core",
    "validators":       "core",
    "config":           "core",
    "hardware":         "core",
    # modules/rf
    "RFScanner":        "modules/rf",
    "rf_config":        "modules/rf",
    "rf_database":      "modules/rf",
    "rf_demod":         "modules/rf",
    "rf_mock":          "modules/rf",
    "rf_module":        "modules/rf",
    "rf_storage":       "modules/rf",
    "adsb_decoder":     "modules/rf",
    "rf_recorder":      "modules/rf",
    "bands":            "modules/rf",
    "dsp":              "modules/rf",
    # modules/network
    "Network":          "modules/network",
    "RadarSentinel":    "modules/network",
    "AdvancedScanner":  "modules/network",
    "SweepModule":      "modules/network",
    "TacticalSniffer":  "modules/network",
    "capture":          "modules/network",
    "bt_module":        "modules/network",
    "WifiAtack":        "modules/network",
    "EvilTwinServer":   "modules/network",
    "WADecryptor":      "modules/network",
    # modules/geo
    "GeoPrecise":       "modules/geo",
    "GeomapSentinel":   "modules/geo",
    "LocatorModule":    "modules/geo",
    "MapSentinel":      "modules/geo",
    # modules/forense
    "ForensicReader":   "modules/forense",
    "ExifAnalyzer":     "modules/forense",
    "MobileSentinel":   "modules/forense",
    "db_extractor":     "modules/forense",
    "Stealth":          "modules/forense",
    # modules/osint
    "OSINTEngine":      "modules/osint",
    "CVEMatcher":       "modules/osint",
    # modules/audit
    "AuditEngine":      "modules/audit",
    "DictionaryManager": "modules/audit",
    "PhishingModule":   "modules/audit",
    "DuckyModule":      "modules/audit",
    # modules/reporte
    "ReportManager":    "modules/reporte",
    "ReportGenerator":  "modules/reporte",
    "MotorReportes":    "modules/reporte",
}


def _paquete_de_archivo(py_file: Path) -> str:
    """Retorna el paquete relativo al root, ej: 'modules/rf'"""
    try:
        rel = py_file.relative_to(ROOT)
        return str(rel.parent).replace("\\", "/")
    except ValueError:
        return ""


def _nuevo_import_from(modulo_importado: str, paquete_origen: str) -> str:
    """
    Decide si un import debe ser relativo o absoluto.
    Si el módulo importado está en el mismo paquete → import relativo (.modulo)
    Si está en otro paquete → import absoluto (paquete.modulo)
    Si es externo (numpy, rich, etc.) → no tocar
    """
    destino = MODULO_A_PAQUETE.get(modulo_importado)
    if destino is None:
        return modulo_importado   # externo — no tocar

    if destino == paquete_origen:
        return f".{modulo_importado}"   # mismo paquete → relativo

    # Otro paquete → absoluto con punto
    paquete_abs = destino.replace("/", ".")
    return f"{paquete_abs}.{modulo_importado}"


def fix_file(py_file: Path, dry_run: bool = False) -> int:
    """
    Corrige los imports de un archivo .py.
    Retorna el número de cambios realizados.
    """
    paquete_origen = _paquete_de_archivo(py_file)

    # Archivos en la raíz (Main.py, etc.) — no tocar imports internos
    if paquete_origen in ("", "."):
        return 0

    try:
        contenido = py_file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0

    lineas = contenido.split("\n")
    nuevas = []
    cambios = 0

    for linea in lineas:
        nueva_linea = linea

        # ── from NombreModulo import Algo ──────────────────────
        m = re.match(r'^(\s*from\s+)(\w+)(\s+import\s+.*)$', linea)
        if m:
            modulo = m.group(2)
            nuevo = _nuevo_import_from(modulo, paquete_origen)
            if nuevo != modulo:
                nueva_linea = m.group(1) + nuevo + m.group(3)

        # ── import NombreModulo ────────────────────────────────
        elif re.match(r'^\s*import\s+\w+', linea):
            for modulo, destino in MODULO_A_PAQUETE.items():
                patron = rf'^(\s*import\s+){re.escape(modulo)}(\s*(?:#.*)?)$'
                if re.match(patron, linea):
                    if destino == paquete_origen:
                        nuevo = f"from . import {modulo}"
                    else:
                        paquete_abs = destino.replace("/", ".")
                        nuevo = f"from {paquete_abs} import {modulo}"
                    nueva_linea = re.sub(
                        patron,
                        nuevo + r'\2',
                        linea
                    )
                    break

        if nueva_linea != linea:
            cambios += 1
        nuevas.append(nueva_linea)

    if cambios > 0 and not dry_run:
        py_file.write_text("\n".join(nuevas), encoding="utf-8")

    return cambios


def crear_pyrightconfig():
    """Crea pyrightconfig.json para que Pylance encuentre los módulos."""
    config = {
        "pythonVersion": "3.13",
        "include": ["."],
        "extraPaths": ["."],
        "reportMissingImports": "warning",
        "reportMissingModuleSource": "none",
        "reportAttributeAccessIssue": "none",
        "reportOptionalMemberAccess": "warning",
        "reportPossiblyUnbound": "warning",
        "typeCheckingMode": "basic"
    }
    dest = ROOT / "pyrightconfig.json"
    dest.write_text(json.dumps(config, indent=4), encoding="utf-8")
    print(f"  [✓] pyrightconfig.json creado en {dest}")


def main():
    dry_run = "--dry-run" in sys.argv
    print(
        f"\n── APEX SENTINEL — Fix Imports {'(DRY-RUN)' if dry_run else ''} ──\n")

    # 1. pyrightconfig.json
    print("1. Configurando Pylance...")
    if not dry_run:
        crear_pyrightconfig()
    else:
        print("  [i] pyrightconfig.json se crearía en la raíz")

    # 2. Corregir imports en subcarpetas
    print("\n2. Corrigiendo imports internos...\n")
    py_files = [f for f in ROOT.rglob("*.py")
                if "__pycache__" not in str(f) and f.name != "fix_imports.py"]

    total_cambios = 0
    for py_file in sorted(py_files):
        cambios = fix_file(py_file, dry_run=dry_run)
        if cambios > 0:
            rel = py_file.relative_to(ROOT)
            print(f"  [✓] {rel} — {cambios} import(s) corregido(s)")
            total_cambios += cambios

    print(f"\n── Resumen ──")
    print(f"  Imports corregidos: {total_cambios}")
    print(f"  pyrightconfig.json: {'creado' if not dry_run else 'simulado'}")

    if dry_run:
        print("\n  Ejecuta sin --dry-run para aplicar.\n")
    else:
        print("\n  ✓ Listo. Recarga VS Code: Ctrl+Shift+P → 'Reload Window'\n")
        print("  Luego verifica: python Main.py\n")


if __name__ == "__main__":
    main()
