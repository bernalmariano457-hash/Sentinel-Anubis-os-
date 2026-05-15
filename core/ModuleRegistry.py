"""
core/ModuleRegistry.py — Registro declarativo de módulos de APEX SENTINEL
══════════════════════════════════════════════════════════════════════════

Reemplaza _cargar_modulos() de Main.py (90 líneas god-method).
Añadir un módulo nuevo = una línea en la lista MODULOS.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Main import ApexSentinel


@dataclass
class ModuleSpec:
    attr:           str          # atributo en el sentinel (self.radar, self.rf…)
    cls_name:       str          # nombre de la clase
    module_path:    str          # ruta Python: "modules.network.RadarSentinel"
    needs_sentinel: bool = True  # True → Cls(sentinel) | False → Cls()
    display_name:   str  = ""    # nombre en bootscreen
    critico:        bool = False

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.cls_name


MODULOS: list[ModuleSpec] = [
    # ── Core ──────────────────────────────────────────────────────────
    ModuleSpec("security",     "SecurityModule",    "core.Security",
               critico=True,  display_name="SecurityModule"),
    ModuleSpec("cola",         "ColaTareas",        "core.ColaTareas",
               display_name="ColaTareas"),
    ModuleSpec("gp",           "GestorProyectos",   "core.GestorProyectos",
               display_name="GestorProyectos"),

    # ── Red ───────────────────────────────────────────────────────────
    ModuleSpec("sniffer",      "TacticalSniffer",   "modules.network.TacticalSniffer",
               display_name="TacticalSniffer"),
    ModuleSpec("radar",        "RadarSentinel",     "modules.network.RadarSentinel",
               display_name="RadarSentinel"),
    ModuleSpec("network",      "Network",           "modules.network.Network",
               display_name="Network"),
    ModuleSpec("adv_scanner",  "AdvancedScanner",   "modules.network.AdvancedScanner",
               display_name="AdvancedScanner"),
    ModuleSpec("sweep",        "SweepModule",       "modules.network.SweepModule",
               display_name="SweepModule"),
    ModuleSpec("wifi_attack",  "WifiAtack",         "modules.network.WifiAtack",
               display_name="WifiAtack"),
    ModuleSpec("bt",           "bt_module",         "modules.network.bt_module",
               display_name="BluetoothModule"),
    ModuleSpec("hydra",        "HydraModule",       "modules.network.HydraModule",
               display_name="HydraModule"),

    # ── Forense ───────────────────────────────────────────────────────
    ModuleSpec("reader",       "ForensicReader",    "modules.forense.ForensicReader",
               display_name="ForensicReader"),
    ModuleSpec("exif",         "ExifAnalyzer",      "modules.forense.ExifAnalyzer",
               display_name="ExifAnalyzer"),
    ModuleSpec("stealth",      "Stealth",           "modules.forense.Stealth",
               display_name="StealthModule"),
    ModuleSpec("mobile",       "MobileSentinel",    "modules.forense.MobileSentinel",
               display_name="MobileSentinel"),

    # ── Geo ───────────────────────────────────────────────────────────
    ModuleSpec("locator",      "LocatorModule",     "modules.geo.LocatorModule",
               display_name="LocatorModule"),
    ModuleSpec("geoprecise",   "GeoPrecise",        "modules.geo.GeoPrecise",
               display_name="GeoPrecise"),
    ModuleSpec("geomap",       "GeomapSentinel",    "modules.geo.GeomapSentinel",
               display_name="GeomapSentinel"),

    # ── Auditoría ─────────────────────────────────────────────────────
    ModuleSpec("audit_engine", "AuditEngine",       "modules.audit.AuditEngine",
               display_name="AuditEngine"),
    ModuleSpec("dict_manager", "DictionaryManager", "modules.audit.DictionaryManager",
               needs_sentinel=False, display_name="DictionaryManager"),
    ModuleSpec("ducky",        "DuckyModule",       "modules.audit.DuckyModule",
               display_name="DuckyModule"),

    # ── Reportes ──────────────────────────────────────────────────────
    ModuleSpec("reportes",     "ReportManager",     "modules.reporte.ReportManager",
               needs_sentinel=False, display_name="ReportManager"),

    # ── OSINT ─────────────────────────────────────────────────────────
    ModuleSpec("osint",        "OSINTEngine",       "modules.osint.OSINTEngine",
               display_name="OSINTEngine"),
    ModuleSpec("cve",          "CVEMatcher",        "modules.osint.CVEMatcher",
               display_name="CVEMatcher"),

    # ── RF ────────────────────────────────────────────────────────────
    ModuleSpec("rf",           "RFModuleIntegrado", "modules.rf.rf_module",
               display_name="RFModuleIntegrado"),
]


class ModuleRegistry:
    """
    Carga todos los módulos declarados en MODULOS y los asigna
    como atributos en el sentinel.
    """

    def __init__(self, sentinel: ApexSentinel) -> None:
        self._sentinel = sentinel
        self._log = getattr(sentinel, "log", None)
        self._resultados: dict[str, tuple[bool, ModuleSpec]] = {}

    def _info(self, msg: str) -> None:
        if self._log:
            self._log.info(msg, "Registry")

    def _warn(self, msg: str) -> None:
        if self._log:
            self._log.warning(msg, "Registry")

    @staticmethod
    def _importar(module_path: str, cls_name: str) -> type[Any] | None:
        try:
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name, None)  # type: ignore[no-any-return]
        except Exception:
            return None

    def _cargar_uno(self, spec: ModuleSpec) -> bool:
        Cls = self._importar(spec.module_path, spec.cls_name)
        if Cls is None:
            self._warn(f"{spec.display_name} — no encontrado en '{spec.module_path}'")
            setattr(self._sentinel, spec.attr, None)
            return False
        try:
            inst = Cls() if not spec.needs_sentinel else Cls(self._sentinel)
            setattr(self._sentinel, spec.attr, inst)
            return True
        except Exception as exc:
            self._warn(f"{spec.display_name} — error al iniciar: {exc}")
            setattr(self._sentinel, spec.attr, None)
            return False

    def _cargar_recovery(self) -> bool:
        sec = getattr(self._sentinel, "security", None)
        if sec is None:
            setattr(self._sentinel, "recovery", None)
            return False
        try:
            from core.Recovery import SentinelRecovery
            setattr(self._sentinel, "recovery", SentinelRecovery(sec))
            return True
        except Exception as exc:
            self._warn(f"SentinelRecovery — error: {exc}")
            setattr(self._sentinel, "recovery", None)
            return False

    def _cargar_motor_rep(self) -> bool:
        if getattr(self._sentinel, "gp", None) is None:
            setattr(self._sentinel, "motor_rep", None)
            return False
        try:
            from modules.reporte.MotorReportes import MotorReportes
            setattr(self._sentinel, "motor_rep", MotorReportes(self._sentinel))
            return True
        except Exception as exc:
            self._warn(f"MotorReportes — error: {exc}")
            setattr(self._sentinel, "motor_rep", None)
            return False

    def _cargar_checker(self) -> bool:
        try:
            from core.SystemChecker import SystemChecker
            console = getattr(self._sentinel, "console", None)
            self._sentinel.checker = SystemChecker(console=console)
            return True
        except Exception as exc:
            self._warn(f"SystemChecker — error: {exc}")
            self._sentinel.checker = None
            return False

    def _cargar_plugins(self) -> bool:
        try:
            from core.PluginSystem import GestorPlugins, crear_plugin_ejemplo
            self._sentinel.plugins = GestorPlugins(self._sentinel)
            crear_plugin_ejemplo()
            self._sentinel.plugins.cargar_todos()
            return True
        except Exception as exc:
            self._warn(f"PluginSystem — error: {exc}")
            self._sentinel.plugins = None
            return False

    def _cargar_extras(self) -> None:
        """Carga callables y primitivas que no son instancias de clase."""
        # EvilTwin
        try:
            from modules.network.EvilTwinServer import iniciar_servidor
            self._sentinel._evil_twin_server = iniciar_servidor
        except Exception:
            self._sentinel._evil_twin_server = None

        # Scapy primitivas
        try:
            from scapy.all import ARP, Ether, srp
            self._sentinel._ARP   = ARP
            self._sentinel._Ether = Ether
            self._sentinel._srp   = srp
        except Exception:
            self._sentinel._ARP = self._sentinel._Ether = self._sentinel._srp = None

        # WADecryptor / DatabaseExtractor (mobile deep)
        try:
            from modules.network.WADecryptor import WADecryptor
            self._sentinel._wa_decryptor_cls = WADecryptor
        except Exception:
            self._sentinel._wa_decryptor_cls = None
        try:
            from modules.forense.db_extractor import DatabaseExtractor
            self._sentinel._db_extractor_cls = DatabaseExtractor
        except Exception:
            self._sentinel._db_extractor_cls = None

    def cargar_todos(self) -> dict[str, bool]:
        """
        Carga todos los módulos en orden correcto de dependencias.
        Devuelve {attr: bool} para el bootscreen.
        """
        resultados: dict[str, bool] = {}
        _especiales = {"recovery", "motor_rep", "plugins", "checker"}

        # 1. checker (necesita console)
        ok = self._cargar_checker()
        resultados["checker"] = ok
        checker_spec = ModuleSpec("checker", "SystemChecker", "core.SystemChecker",
                                  display_name="SystemChecker", critico=False)
        self._resultados["checker"] = (ok, checker_spec)

        # 2. Módulos del catálogo (excepto especiales)
        for spec in MODULOS:
            if spec.attr in _especiales:
                continue
            ok = self._cargar_uno(spec)
            resultados[spec.attr] = ok
            self._resultados[spec.attr] = (ok, spec)

        # 3. Recovery (depende de security)
        ok = self._cargar_recovery()
        resultados["recovery"] = ok
        rec_spec = ModuleSpec("recovery", "SentinelRecovery", "core.Recovery",
                              display_name="SentinelRecovery")
        self._resultados["recovery"] = (ok, rec_spec)

        # 4. MotorReportes (depende de gp)
        ok = self._cargar_motor_rep()
        resultados["motor_rep"] = ok
        mr_spec = ModuleSpec("motor_rep", "MotorReportes",
                             "modules.reporte.MotorReportes",
                             display_name="MotorReportes")
        self._resultados["motor_rep"] = (ok, mr_spec)

        # 5. Plugins
        ok = self._cargar_plugins()
        resultados["plugins"] = ok

        # 6. Extras (callables/primitivas)
        self._cargar_extras()

        n_ok = sum(1 for v in resultados.values() if v)
        self._info(f"Módulos cargados: {n_ok}/{len(resultados)}")
        return resultados

    def estados(self) -> dict[str, bool]:
        """Para el bootscreen: {display_name: bool}"""
        return {spec.display_name: ok
                for _attr, (ok, spec) in self._resultados.items()}

    def disponible(self, attr: str) -> bool:
        return getattr(self._sentinel, attr, None) is not None
