import argparse
import re
import shutil
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════════
# MAPA DE MIGRACIÓN
# archivo_origen → módulo/destino
# ══════════════════════════════════════════════════════════════════

MAPA: dict[str, str] = {
    # ── core ──────────────────────────────────────────────────────
    "auth.py":             "core/auth.py",
    "Security.py":         "core/Security.py",
    "ColaTareas.py":       "core/ColaTareas.py",
    "GestorProyectos.py":  "core/GestorProyectos.py",
    "bootscreen.py":       "core/bootscreen.py",
    "command_handler.py":  "core/command_handler.py",
    "logger.py":           "core/logger.py",
    "log_sistema.py":      "core/log_sistema.py",
    "log_visual.py":       "core/log_visual.py",
    "PluginSystem.py":     "core/PluginSystem.py",
    "SystemChecker.py":    "core/SystemChecker.py",
    "Recovery.py":         "core/Recovery.py",
    "validators.py":       "core/validators.py",
    "config.py":           "core/config.py",
    "hardware.py":         "core/hardware.py",

    # ── modules/rf ────────────────────────────────────────────────
    "RFScanner.py":        "modules/rf/RFScanner.py",
    "rf_config.py":        "modules/rf/rf_config.py",
    "rf_database.py":      "modules/rf/rf_database.py",
    "rf_demod.py":         "modules/rf/rf_demod.py",
    "rf_mock.py":          "modules/rf/rf_mock.py",
    "rf_module.py":        "modules/rf/rf_module.py",
    "rf_storage.py":       "modules/rf/rf_storage.py",
    "adsb_decoder.py":     "modules/rf/adsb_decoder.py",
    "rf_recorder.py":      "modules/rf/rf_recorder.py",
    "bands.py":            "modules/rf/bands.py",
    "dsp.py":              "modules/rf/dsp.py",

    # ── modules/network ───────────────────────────────────────────
    "Network.py":          "modules/network/Network.py",
    "RadarSentinel.py":    "modules/network/RadarSentinel.py",
    "AdvancedScanner.py":  "modules/network/AdvancedScanner.py",
    "SweepModule.py":      "modules/network/SweepModule.py",
    "TacticalSniffer.py":  "modules/network/TacticalSniffer.py",
    "capture.py":          "modules/network/capture.py",
    "bt_module.py":        "modules/network/bt_module.py",
    "WifiAtack.py":        "modules/network/WifiAtack.py",
    "EvilTwinServer.py":   "modules/network/EvilTwinServer.py",
    "WADecryptor.py":      "modules/network/WADecryptor.py",

    # ── modules/geo ───────────────────────────────────────────────
    "GeoPrecise.py":       "modules/geo/GeoPrecise.py",
    "GeomapSentinel.py":   "modules/geo/GeomapSentinel.py",
    "LocatorModule.py":    "modules/geo/LocatorModule.py",
    "MapSentienel.py":     "modules/geo/MapSentinel.py",   # typo corregido

    # ── modules/forense ───────────────────────────────────────────
    "ForensicReader.py":   "modules/forense/ForensicReader.py",
    "ExifAnalyzer.py":     "modules/forense/ExifAnalyzer.py",
    "MobileSentinel.py":   "modules/forense/MobileSentinel.py",
    "db_extractor.py":     "modules/forense/db_extractor.py",
    "Stealth.py":          "modules/forense/Stealth.py",

    # ── modules/osint ─────────────────────────────────────────────
    "OSINTEngine.py":      "modules/osint/OSINTEngine.py",
    "CVEMatcher.py":       "modules/osint/CVEMatcher.py",

    # ── modules/audit ─────────────────────────────────────────────
    "AuditEngine.py":      "modules/audit/AuditEngine.py",
    "DictionaryManager.py": "modules/audit/DictionaryManager.py",
    "PhishingModule.py":   "modules/audit/PhishingModule.py",
    "DuckyModule.py":      "modules/audit/DuckyModule.py",

    # ── modules/reporte ───────────────────────────────────────────
    "ReportManager.py":    "modules/reporte/ReportManager.py",
    "ReportGenerator.py":  "modules/reporte/ReportGenerator.py",
    "MotorReportes.py":    "modules/reporte/MotorReportes.py",

    # ── tools ─────────────────────────────────────────────────────
    "sentinel_setup.py":   "tools/sentinel_setup.py",
    "test_rfscanner.py":   "tools/test_rfscanner.py",
    "test_sentinel.py":    "tools/test_sentinel.py",
}

# Archivos que se quedan en raíz (punto de entrada + config)
RAIZ = {"Main.py", "config.json", "default.toml", "requirements.txt",
        ".gitignore", ".env.example", "README.md", "__init__.py"}

# Carpetas a crear con su __init__.py
PAQUETES = [
    "core",
    "modules",
    "modules/rf",
    "modules/network",
    "modules/geo",
    "modules/forense",
    "modules/osint",
    "modules/audit",
    "modules/reporte",
    "tools",
]

# ══════════════════════════════════════════════════════════════════
# ACTUALIZACIÓN DE IMPORTS
# ══════════════════════════════════════════════════════════════════

# Mapa inverso: nombre_clase/módulo → nuevo import path
IMPORT_MAP: dict[str, str] = {
    # core
    "auth":              "core.auth",
    "Security":          "core.Security",
    "ColaTareas":        "core.ColaTareas",
    "GestorProyectos":   "core.GestorProyectos",
    "bootscreen":        "core.bootscreen",
    "command_handler":   "core.command_handler",
    "logger":            "core.logger",
    "log_sistema":       "core.log_sistema",
    "log_visual":        "core.log_visual",
    "PluginSystem":      "core.PluginSystem",
    "SystemChecker":     "core.SystemChecker",
    "Recovery":          "core.Recovery",
    "validators":        "core.validators",
    "config":            "core.config",
    "hardware":          "core.hardware",
    # rf
    "RFScanner":         "modules.rf.RFScanner",
    "rf_config":         "modules.rf.rf_config",
    "rf_database":       "modules.rf.rf_database",
    "rf_demod":          "modules.rf.rf_demod",
    "rf_mock":           "modules.rf.rf_mock",
    "rf_module":         "modules.rf.rf_module",
    "rf_storage":        "modules.rf.rf_storage",
    "adsb_decoder":      "modules.rf.adsb_decoder",
    "rf_recorder":       "modules.rf.rf_recorder",
    "bands":             "modules.rf.bands",
    "dsp":               "modules.rf.dsp",
    # network
    "Network":           "modules.network.Network",
    "RadarSentinel":     "modules.network.RadarSentinel",
    "AdvancedScanner":   "modules.network.AdvancedScanner",
    "SweepModule":       "modules.network.SweepModule",
    "TacticalSniffer":   "modules.network.TacticalSniffer",
    "capture":           "modules.network.capture",
    "bt_module":         "modules.network.bt_module",
    "WifiAtack":         "modules.network.WifiAtack",
    "EvilTwinServer":    "modules.network.EvilTwinServer",
    "WADecryptor":       "modules.network.WADecryptor",
    # geo
    "GeoPrecise":        "modules.geo.GeoPrecise",
    "GeomapSentinel":    "modules.geo.GeomapSentinel",
    "LocatorModule":     "modules.geo.LocatorModule",
    "MapSentienel":      "modules.geo.MapSentinel",
    # forense
    "ForensicReader":    "modules.forense.ForensicReader",
    "ExifAnalyzer":      "modules.forense.ExifAnalyzer",
    "MobileSentinel":    "modules.forense.MobileSentinel",
    "db_extractor":      "modules.forense.db_extractor",
    "Stealth":           "modules.forense.Stealth",
    # osint
    "OSINTEngine":       "modules.osint.OSINTEngine",
    "CVEMatcher":        "modules.osint.CVEMatcher",
    # audit
    "AuditEngine":       "modules.audit.AuditEngine",
    "DictionaryManager": "modules.audit.DictionaryManager",
    "PhishingModule":    "modules.audit.PhishingModule",
    "DuckyModule":       "modules.audit.DuckyModule",
    # reporte
    "ReportManager":     "modules.reporte.ReportManager",
    "ReportGenerator":   "modules.reporte.ReportGenerator",
    "MotorReportes":     "modules.reporte.MotorReportes",
}


def _actualizar_imports(contenido: str) -> tuple[str, int]:
    """
    Reemplaza imports planos por imports con ruta de módulo.
    Retorna (contenido_actualizado, número_de_cambios).
    """
    cambios = 0
    lineas = contenido.split("\n")
    nuevas = []

    for linea in lineas:
        original = linea

        # Caso: from NombreModulo import Algo
        m = re.match(r'^(\s*from\s+)(\w+)(\s+import\s+.*)$', linea)
        if m and m.group(2) in IMPORT_MAP:
            linea = m.group(1) + IMPORT_MAP[m.group(2)] + m.group(3)

        # Caso: import NombreModulo
        elif re.match(r'^\s*import\s+\w+', linea):
            for nombre, nuevo in IMPORT_MAP.items():
                patron = rf'^(\s*import\s+){re.escape(nombre)}(\s*(?:#.*)?)$'
                reemplazo = rf'\g<1>{nuevo}\2'
                nueva = re.sub(patron, reemplazo, linea)
                if nueva != linea:
                    linea = nueva
                    break

        if linea != original:
            cambios += 1
        nuevas.append(linea)

    return "\n".join(nuevas), cambios


# ══════════════════════════════════════════════════════════════════
# MIGRACIÓN
# ══════════════════════════════════════════════════════════════════

def migrar(repo: Path, dry_run: bool = False):
    """Ejecuta la migración completa del repositorio."""

    print(f"\n{'─'*60}")
    print(f"  APEX SENTINEL — Migración a estructura modular")
    print(f"  Repositorio: {repo}")
    print(f"  Modo: {'DRY-RUN (simulación)' if dry_run else 'REAL'}")
    print(f"{'─'*60}\n")

    if not repo.exists():
        print(f"[!] No se encontró el directorio: {repo}")
        sys.exit(1)

    # 1. Crear estructura de carpetas
    print("── 1. Creando estructura de carpetas ──")
    for paquete in PAQUETES:
        carpeta = repo / paquete
        init = carpeta / "__init__.py"
        if not dry_run:
            carpeta.mkdir(parents=True, exist_ok=True)
            if not init.exists():
                init.write_text(
                    f'"""APEX SENTINEL — {paquete.replace("/", ".")}"""\n',
                    encoding="utf-8",
                )
        print(f"  [+] {paquete}/__init__.py")

    # 2. Mover archivos
    print("\n── 2. Moviendo archivos ──")
    movidos = 0
    no_encontrados = []

    for origen_nombre, destino_rel in MAPA.items():
        origen = repo / origen_nombre
        destino = repo / destino_rel

        if not origen.exists():
            no_encontrados.append(origen_nombre)
            continue

        if not dry_run:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))

        print(f"  [→] {origen_nombre:35s} → {destino_rel}")
        movidos += 1

    if no_encontrados:
        print(f"\n  [i] No encontrados (pueden ser nuevos o ya movidos):")
        for f in no_encontrados:
            print(f"      · {f}")

    # 3. Actualizar imports en todos los .py
    print("\n── 3. Actualizando imports ──")
    py_files = list(repo.rglob("*.py"))
    py_files = [f for f in py_files if "__pycache__" not in str(f)]
    total_cambios = 0

    for py_file in py_files:
        try:
            contenido = py_file.read_text(encoding="utf-8")
            nuevo, cambios = _actualizar_imports(contenido)
            if cambios > 0:
                if not dry_run:
                    py_file.write_text(nuevo, encoding="utf-8")
                print(
                    f"  [✓] {py_file.relative_to(repo)} — {cambios} import(s) actualizado(s)")
                total_cambios += cambios
        except (UnicodeDecodeError, OSError) as e:
            print(f"  [!] No se pudo procesar {py_file.name}: {e}")

    # 4. Limpiar __pycache__ obsoleto
    print("\n── 4. Limpiando caché Python ──")
    for cache in repo.rglob("__pycache__"):
        if not dry_run:
            shutil.rmtree(cache, ignore_errors=True)
        print(f"  [×] {cache.relative_to(repo)}")

    # 5. Resumen
    print(f"\n{'─'*60}")
    print(
        f"  {'[DRY-RUN] Simulación completada' if dry_run else 'Migración completada'}")
    print(f"  Archivos movidos:        {movidos}")
    print(f"  Imports actualizados:    {total_cambios}")
    print(f"  Carpetas creadas:        {len(PAQUETES)}")
    print(f"{'─'*60}\n")

    if dry_run:
        print("  Ejecuta sin --dry-run para aplicar los cambios.\n")
    else:
        print("  ✓ Siguiente paso: python Main.py para verificar arranque.\n")


def verificar(repo: Path):
    """Verifica que la estructura modular es correcta."""
    print(f"\n── Verificando estructura en {repo} ──\n")
    errores = 0

    for paquete in PAQUETES:
        init = repo / paquete / "__init__.py"
        if init.exists():
            print(f"  [✓] {paquete}/__init__.py")
        else:
            print(f"  [!] FALTA: {paquete}/__init__.py")
            errores += 1

    for origen, destino in MAPA.items():
        dest = repo / destino
        if dest.exists():
            print(f"  [✓] {destino}")
        else:
            print(f"  [!] FALTA: {destino}  (era: {origen})")
            errores += 1

    print(
        f"\n  {'✓ Todo correcto' if errores == 0 else f'⚠ {errores} problema(s) encontrado(s)'}\n")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migración de APEX SENTINEL a estructura modular"
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="Ruta al repositorio Sentinel (default: directorio actual)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula la migración sin hacer cambios",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verifica que la estructura modular sea correcta",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()

    if args.verify:
        verificar(repo)
    else:
        migrar(repo, dry_run=args.dry_run)
