from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass
class ModuleSpec:
    attr:           str
    cls_name:       str
    module_path:    str
    needs_sentinel: bool = True
    display_name:   str = ""
    critico:        bool = False

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.cls_name


MODULOS: list[ModuleSpec] = [
    ModuleSpec("security",     "SecurityModule",    "core.Security",
               critico=True,  display_name="SecurityModule"),
    ModuleSpec("cola",         "ColaTareas",        "core.ColaTareas"),
    ModuleSpec("gp",           "GestorProyectos",   "core.GestorProyectos"),

    ModuleSpec("sniffer",      "TacticalSniffer",
               "modules.network.TacticalSniffer"),
    ModuleSpec("radar",        "RadarSentinel",
               "modules.network.RadarSentinel"),
    ModuleSpec("network",      "Network",           "modules.network.Network"),
    ModuleSpec("adv_scanner",  "AdvancedScanner",
               "modules.network.AdvancedScanner"),
    ModuleSpec("sweep",        "SweepModule",
               "modules.network.SweepModule"),
    ModuleSpec("wifi_attack",  "WifiAtack",
               "modules.network.WifiAtack"),
    ModuleSpec("bt",           "bt_module",         "modules.network.bt_module",
               display_name="BluetoothModule"),
    ModuleSpec("hydra",        "HydraModule",
               "modules.network.HydraModule"),
    ModuleSpec("wifitri",      "WiFiTriangulation",  "modules.network.wifi_triangulation",
               display_name="WiFi Triangulation"),

    ModuleSpec("reader",       "ForensicReader",
               "modules.forense.ForensicReader"),
    ModuleSpec("exif",         "ExifAnalyzer",
               "modules.forense.ExifAnalyzer"),
    ModuleSpec("stealth",      "Stealth",           "modules.forense.Stealth",
               display_name="StealthModule"),
    ModuleSpec("mobile",       "MobileSentinel",
               "modules.forense.MobileSentinel"),

    ModuleSpec("locator",      "LocatorModule",
               "modules.geo.LocatorModule"),
    ModuleSpec("geoprecise",   "GeoPrecise",        "modules.geo.GeoPrecise"),
    ModuleSpec("geomap",       "GeomapSentinel",
               "modules.geo.GeomapSentinel"),

    ModuleSpec("audit_engine", "AuditEngine",
               "modules.audit.AuditEngine"),
    ModuleSpec("dict_manager", "DictionaryManager", "modules.audit.DictionaryManager",
               needs_sentinel=False),
    ModuleSpec("ducky",        "DuckyModule",
               "modules.audit.DuckyModule"),

    ModuleSpec("reportes",     "ReportManager",     "modules.reporte.ReportManager",
               needs_sentinel=False),


    ModuleSpec("osint",        "OSINTEngine",
               "modules.osint.OSINTEngine"),
    ModuleSpec("cve",          "CVEMatcher",
               "modules.osint.CVEMatcher"),

    ModuleSpec("rf",           "RFModuleIntegrado", "modules.rf.rf_module"),
    ModuleSpec("sa",           "SpectrumAnalyzer",
               "modules.rf.SpectrumAnalyzer"),
    ModuleSpec("adsb",         "AircraftMonitor",   "modules.rf.adsb_pymodes",
               display_name="ADS-B pyModeS"),
    ModuleSpec("noaa",         "NOAADecoder",       "modules.rf.NOAADecoder"),
]


class ModuleRegistry:

    def __init__(self, sentinel):
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
    def _importar(module_path: str, cls_name: str):
        try:
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name, None)
        except Exception:
            return None

    def _cargar_uno(self, spec: ModuleSpec) -> bool:
        Cls = self._importar(spec.module_path, spec.cls_name)
        if Cls is None:
            self._warn(
                f"{spec.display_name} — no encontrado en '{spec.module_path}'")
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
            self._sentinel.checker = SystemChecker(
                console=getattr(self._sentinel, "console", None))
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

        try:
            from modules.network.EvilTwinServer import iniciar_servidor
            self._sentinel._evil_twin_server = iniciar_servidor
        except Exception:
            self._sentinel._evil_twin_server = None

        try:
            from scapy.all import ARP, Ether, srp
            self._sentinel._ARP = ARP
            self._sentinel._Ether = Ether
            self._sentinel._srp = srp
        except Exception:
            self._sentinel._ARP = self._sentinel._Ether = self._sentinel._srp = None

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
        resultados: dict[str, bool] = {}
        _especiales = {"recovery", "motor_rep", "plugins", "checker"}

        ok = self._cargar_checker()
        resultados["checker"] = ok
        self._resultados["checker"] = (ok, ModuleSpec(
            "checker", "SystemChecker", "core.SystemChecker"))

        for spec in MODULOS:
            if spec.attr in _especiales:
                continue
            ok = self._cargar_uno(spec)
            resultados[spec.attr] = ok
            self._resultados[spec.attr] = (ok, spec)

        ok = self._cargar_recovery()
        resultados["recovery"] = ok
        self._resultados["recovery"] = (ok, ModuleSpec(
            "recovery", "SentinelRecovery", "core.Recovery"))

        ok = self._cargar_motor_rep()
        resultados["motor_rep"] = ok
        self._resultados["motor_rep"] = (ok, ModuleSpec(
            "motor_rep", "MotorReportes", "modules.reporte.MotorReportes"))

        ok = self._cargar_plugins()
        resultados["plugins"] = ok

        self._cargar_extras()

        n_ok = sum(1 for v in resultados.values() if v)
        self._info(f"Módulos cargados: {n_ok}/{len(resultados)}")
        return resultados

    def estados(self) -> dict[str, bool]:
        return {spec.display_name: ok
                for attr, (ok, spec) in self._resultados.items()}

    def disponible(self, attr: str) -> bool:
        return getattr(self._sentinel, attr, None) is not None
