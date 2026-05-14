from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Asegurar que el proyecto está en el path ──────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ════════════════════════════════════════════════════════════════════
# FIXTURES COMPARTIDOS
# ════════════════════════════════════════════════════════════════════

@pytest.fixture
def console():
    from rich.console import Console
    return Console(quiet=True)   # silencia output en tests


@pytest.fixture
def mock_log():
    """Log falso que no escribe nada en disco."""
    log = MagicMock()
    log.info = MagicMock()
    log.warning = MagicMock()
    log.error = MagicMock()
    log.success = MagicMock()
    log.audit = MagicMock()
    return log


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


# ════════════════════════════════════════════════════════════════════
# TESTS — VALIDADOR
# ════════════════════════════════════════════════════════════════════

class TestValidador:

    def setup_method(self):
        from core.validators import Validador
        self.V = Validador

    # IPs
    def test_ip_valida_v4(self):
        assert self.V.es_ip("192.168.1.1")

    def test_ip_valida_v6(self):
        assert self.V.es_ip("::1")

    def test_ip_invalida_texto(self):
        assert not self.V.es_ip("no-es-ip")

    def test_ip_invalida_rango(self):
        assert not self.V.es_ip("999.999.999.999")

    def test_ip_vacia(self):
        assert not self.V.es_ip("")

    # CIDR
    def test_cidr_valido(self):
        assert self.V.es_rango_cidr("192.168.0.0/24")

    def test_cidr_host_valido(self):
        assert self.V.es_rango_cidr("10.0.0.1/32")

    def test_cidr_invalido(self):
        assert not self.V.es_rango_cidr("300.0.0.0/24")

    def test_cidr_sin_mascara(self):
        # Una IP sola es un /32 implícito — válido
        assert self.V.es_rango_cidr("192.168.1.1")

    # MAC
    def test_mac_valida(self):
        assert self.V.es_mac("AA:BB:CC:DD:EE:FF")

    def test_mac_minusculas(self):
        assert self.V.es_mac("aa:bb:cc:dd:ee:ff")

    def test_mac_invalida_corta(self):
        assert not self.V.es_mac("AA:BB:CC")

    def test_mac_invalida_guion(self):
        assert not self.V.es_mac("AA-BB-CC-DD-EE-FF")

    def test_mac_vacia(self):
        assert not self.V.es_mac("")

    # URL
    def test_url_http(self):
        assert self.V.es_url("http://ejemplo.com")

    def test_url_https_con_path(self):
        assert self.V.es_url("https://target.com/login?id=1")

    def test_url_sin_protocolo(self):
        assert not self.V.es_url("ejemplo.com")

    def test_url_ftp_invalida(self):
        assert not self.V.es_url("ftp://ejemplo.com")

    def test_url_vacia(self):
        assert not self.V.es_url("")

    # Frecuencia
    def test_frecuencia_valida(self):
        assert self.V.es_frecuencia("433.92")

    def test_frecuencia_limite_inferior(self):
        assert self.V.es_frecuencia("1.0")

    def test_frecuencia_limite_superior(self):
        assert self.V.es_frecuencia("6000.0")

    def test_frecuencia_fuera_rango_bajo(self):
        assert not self.V.es_frecuencia("0.5")

    def test_frecuencia_fuera_rango_alto(self):
        assert not self.V.es_frecuencia("9999.0")

    def test_frecuencia_texto(self):
        assert not self.V.es_frecuencia("abc")

    def test_frecuencia_vacia(self):
        assert not self.V.es_frecuencia("")


# ════════════════════════════════════════════════════════════════════
# TESTS — AUTENTICACIÓN
# ════════════════════════════════════════════════════════════════════

class TestGestorAuth:
    @pytest.fixture
    def auth(self, console, mock_log):
        from core.auth import GestorAuth
        config = {"sistema": {"nombre": "Test", "version": "1.0",
                              "primer_arranque": False}}
        return GestorAuth(config, console, mock_log)

    # Hashing
    def test_hash_genera_string(self, auth):
        h = auth._hash("clave123")
        assert isinstance(h, str)
        assert len(h) > 0

    def test_hash_distinto_cada_vez(self, auth):
        h1 = auth._hash("misma_clave")
        h2 = auth._hash("misma_clave")
        # bcrypt genera salt diferente cada vez
        assert h1 != h2

    # Verificación SHA-256 legacy (64 hex chars, sin salt)
    def test_verificar_legacy_sha256(self, auth):
        pwd = "testpass"
        hash_legacy = hashlib.sha256(pwd.encode()).hexdigest()
        assert len(hash_legacy) == 64
        assert auth._verificar(pwd, hash_legacy)

    def test_verificar_legacy_sha256_incorrecto(self, auth):
        hash_legacy = hashlib.sha256("correcto".encode()).hexdigest()
        assert not auth._verificar("incorrecto", hash_legacy)

    # Verificación SHA-256 con salt (formato nuevo sin bcrypt)
    def test_verificar_sha256_con_salt(self, auth):
        import os as _os
        pwd = "clave_test"
        salt = _os.urandom(16).hex()
        h = hashlib.sha256((salt + pwd).encode()).hexdigest()
        almacenado = f"{salt}:{h}"
        assert auth._verificar(pwd, almacenado)

    def test_verificar_sha256_con_salt_incorrecto(self, auth):
        import os as _os
        salt = _os.urandom(16).hex()
        h = hashlib.sha256((salt + "correcto").encode()).hexdigest()
        almacenado = f"{salt}:{h}"
        assert not auth._verificar("incorrecto", almacenado)

    # Verificación round-trip (hash → verify)
    def test_hash_y_verificar_correcto(self, auth):
        pwd = "MiClave@Segura123"
        h = auth._hash(pwd)
        assert auth._verificar(pwd, h)

    def test_hash_y_verificar_incorrecto(self, auth):
        h = auth._hash("la_buena")
        assert not auth._verificar("la_mala", h)

    # solicitar_acceso con hash en config
    def test_solicitar_acceso_correcto(self, console, mock_log):
        from core.auth import GestorAuth
        import hashlib
        pwd = "acceso123"
        salt = "deadbeef"
        h_str = hashlib.sha256((salt + pwd).encode()).hexdigest()
        config = {"sistema": {
            "password_hash": f"{salt}:{h_str}",
            "primer_arranque": False,
        }}
        auth = GestorAuth(config, console, mock_log)
        with patch("auth.Prompt.ask", return_value=pwd):
            resultado = auth.solicitar_acceso()
        assert resultado is True

    def test_solicitar_acceso_agota_intentos(self, console, mock_log):
        from core.auth import GestorAuth
        import hashlib
        salt = "cafebabe"
        h_str = hashlib.sha256((salt + "correcta").encode()).hexdigest()
        config = {"sistema": {
            "password_hash": f"{salt}:{h_str}",
            "primer_arranque": False,
        }}
        auth = GestorAuth(config, console, mock_log)
        with patch("auth.Prompt.ask", return_value="incorrecta"):
            resultado = auth.solicitar_acceso()
        assert resultado is False


# ════════════════════════════════════════════════════════════════════
# TESTS — LOG SISTEMA
# ════════════════════════════════════════════════════════════════════

class TestLogSistema:

    @pytest.fixture
    def log(self, console, tmp_dir, monkeypatch):
        monkeypatch.chdir(tmp_dir)
        from core.log_sistema import LogSistema
        return LogSistema(console)

    def test_info_no_lanza(self, log):
        log.info("mensaje de prueba", "TestModulo")

    def test_warning_no_lanza(self, log):
        log.warning("advertencia", "TestModulo")

    def test_error_no_lanza(self, log):
        log.error("error de prueba", "TestModulo")

    def test_audit_no_lanza(self, log):
        log.audit("evento auditado", "TestModulo")

    def test_entradas_se_acumulan(self, log):
        inicial = len(log._entradas)
        log.info("msg1", "M")
        log.info("msg2", "M")
        assert len(log._entradas) == inicial + 2

    def test_estructura_entrada(self, log):
        log.info("test", "ModX")
        entrada = log._entradas[-1]
        assert "timestamp" in entrada
        assert "nivel" in entrada
        assert "modulo" in entrada
        assert "mensaje" in entrada
        assert entrada["nivel"] == "INFO"
        assert entrada["modulo"] == "ModX"
        assert entrada["mensaje"] == "test"

    def test_historial_json_se_crea(self, log, tmp_dir):
        log.info("persistencia", "Test")
        ruta = tmp_dir / "data" / "logs" / "historial.json"
        assert ruta.exists()

    def test_historial_json_es_valido(self, log, tmp_dir):
        log.info("json check", "Test")
        ruta = tmp_dir / "data" / "logs" / "historial.json"
        data = json.loads(ruta.read_text())
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_verificar_y_limpiar(self, log):
        for i in range(600):
            log._entradas.append({"timestamp": "", "nivel": "INFO",
                                  "modulo": "T", "mensaje": str(i)})
        log.verificar_y_limpiar(max_entradas=500)
        assert len(log._entradas) <= 500

    def test_mostrar_historial_vacio(self, log):
        log._entradas.clear()
        log.mostrar_historial()   # No debe lanzar excepción


# ════════════════════════════════════════════════════════════════════
# TESTS — COLA DE TAREAS
# ════════════════════════════════════════════════════════════════════

class TestColaTareas:

    @pytest.fixture
    def cola(self):
        from core.ColaTareas import ColaTareas
        return ColaTareas()

    def test_agregar_tarea_retorna_id(self, cola):
        tid = cola.agregar("prueba", lambda: None)
        assert tid is not None
        assert len(tid) > 0

    def test_tarea_se_ejecuta(self, cola):
        resultado = []
        cola.agregar("tarea_exec", lambda: resultado.append(1))
        time.sleep(0.3)
        assert resultado == [1]

    def test_tarea_con_error_marca_estado(self, cola):
        def lanza():
            raise ValueError("error intencional")
        tid = cola.agregar("tarea_error", lanza)
        time.sleep(0.3)
        from core.ColaTareas import EstadoTarea
        tarea = cola._tareas.get(tid)
        assert tarea is not None
        assert tarea.estado == EstadoTarea.ERROR

    def test_limpiar_completadas(self, cola):
        cola.agregar("t1", lambda: None)
        cola.agregar("t2", lambda: None)
        time.sleep(0.3)
        cola.limpiar_completadas()
        from core.ColaTareas import EstadoTarea
        for t in cola._tareas.values():
            assert t.estado != EstadoTarea.COMPLETADA

    def test_listar_no_lanza(self, cola):
        cola.agregar("listar_test", lambda: None)
        time.sleep(0.1)
        cola.listar()   # No debe lanzar

    def test_resultado_tarea_exitosa(self, cola):
        tid = cola.agregar("retorna_42", lambda: 42)
        time.sleep(0.3)
        tarea = cola._tareas.get(tid)
        assert tarea.resultado == 42

    def test_multiples_tareas_paralelas(self, cola):
        resultados = []
        lock = threading.Lock()

        def trabajo(n):
            time.sleep(0.05)
            with lock:
                resultados.append(n)

        for i in range(5):
            cola.agregar(f"paralela_{i}", trabajo, args=(i,))
        time.sleep(0.5)
        assert len(resultados) == 5


# ════════════════════════════════════════════════════════════════════
# TESTS — GESTOR DE PROYECTOS
# ════════════════════════════════════════════════════════════════════

class TestGestorProyectos:

    @pytest.fixture
    def gp(self, tmp_dir, monkeypatch):
        monkeypatch.chdir(tmp_dir)
        import GestorProyectos as gp_mod
        monkeypatch.setattr(gp_mod, "PROYECTOS_PATH",
                            str(tmp_dir / "data" / "proyectos"))
        from core.GestorProyectos import GestorProyectos
        return GestorProyectos()

    @pytest.fixture
    def proyecto_activo(self, gp):
        from core.GestorProyectos import Proyecto
        p = Proyecto("TestOp", "Objetivo de prueba",
                     "192.168.1.0/24", "red-interna")
        gp.proyecto_activo = p
        os.makedirs(p.ruta, exist_ok=True)
        gp._guardar_proyecto()
        return p

    def test_crear_proyecto_objeto(self, tmp_dir):
        from core.GestorProyectos import Proyecto
        p = Proyecto("Op1", "Objetivo", "10.0.0.0/8", "web")
        assert p.nombre == "Op1"
        assert p.objetivo == "Objetivo"
        assert p.scope == "10.0.0.0/8"
        assert p.estado == "activo"
        assert isinstance(p.evidencias, list)
        assert isinstance(p.hallazgos, list)

    def test_proyecto_to_dict(self, tmp_dir):
        from core.GestorProyectos import Proyecto
        p = Proyecto("TestDict", "Obj", "10.0.0.0/8")
        d = p.to_dict()
        for campo in ["id", "nombre", "objetivo", "scope", "estado",
                      "evidencias", "hallazgos", "creado"]:
            assert campo in d

    def test_proyecto_from_dict_roundtrip(self):
        from core.GestorProyectos import Proyecto
        p = Proyecto("RoundTrip", "Objetivo", "192.168.0.0/16", "forense")
        d = p.to_dict()
        p2 = Proyecto.from_dict(d)
        assert p2.nombre == p.nombre
        assert p2.objetivo == p.objetivo
        assert p2.scope == p.scope
        assert p2.tipo == p.tipo

    def test_registrar_evidencia(self, gp, proyecto_activo):
        gp.registrar_evidencia("arp_scan", "Scan de red local",
                               {"hosts": 5, "rango": "192.168.1.0/24"})
        assert len(proyecto_activo.evidencias) == 1
        ev = proyecto_activo.evidencias[0]
        assert ev["tipo"] == "arp_scan"
        assert ev["descripcion"] == "Scan de red local"
        assert "timestamp" in ev

    def test_registrar_hallazgo(self, gp, proyecto_activo):
        gp.registrar_hallazgo("ALTO", "Puerto 22 abierto",
                              "SSH en servidor de producción",
                              "Cambiar puerto o restringir acceso.")
        assert len(proyecto_activo.hallazgos) == 1
        h = proyecto_activo.hallazgos[0]
        assert h["severidad"] == "ALTO"
        assert h["titulo"] == "Puerto 22 abierto"

    def test_guardar_y_cargar_proyecto(self, gp, proyecto_activo, tmp_dir):
        gp.registrar_evidencia("test", "evidencia", {})
        gp._guardar_proyecto()

        from core.GestorProyectos import GestorProyectos
        gp2 = GestorProyectos()
        proyectos = gp2.listar_proyectos(mostrar=False)
        nombres = [p["nombre"] for p in proyectos]
        assert "TestOp" in nombres

    def test_sin_proyecto_activo_registrar_evidencia(self, gp):
        gp.proyecto_activo = None
        # No debe lanzar excepción
        gp.registrar_evidencia("test", "sin proyecto activo", {})

    def test_multiples_evidencias(self, gp, proyecto_activo):
        for i in range(5):
            gp.registrar_evidencia(f"tipo_{i}", f"evidencia {i}", {"n": i})
        assert len(proyecto_activo.evidencias) == 5


# ════════════════════════════════════════════════════════════════════
# TESTS — PLUGIN SYSTEM
# ════════════════════════════════════════════════════════════════════

class TestPluginSystem:

    @pytest.fixture
    def sentinel_mock(self, console):
        s = MagicMock()
        s.console = console
        return s

    @pytest.fixture
    def gestor(self, sentinel_mock, tmp_dir, monkeypatch):
        monkeypatch.chdir(tmp_dir)
        import PluginSystem as ps_mod
        monkeypatch.setattr(ps_mod, "PLUGINS_PATH", str(tmp_dir / "plugins"))
        from core.PluginSystem import GestorPlugins
        return GestorPlugins(sentinel_mock)

    @pytest.fixture
    def plugin_archivo(self, tmp_dir, monkeypatch):
        import PluginSystem as ps_mod
        plugins_dir = tmp_dir / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(ps_mod, "PLUGINS_PATH", str(plugins_dir))

        contenido = '''
from core.PluginSystem import PluginBase

class PluginTest(PluginBase):
    NOMBRE = "plugin_test"
    VERSION = "1.0"
    DESCRIPCION = "Plugin de prueba para tests"
    AUTOR = "TestSuite"
    COMANDOS = ["test_cmd", "test_cmd2"]

    def ejecutar(self, comando, args=None):
        return f"ejecutado:{comando}"
'''
        archivo = plugins_dir / "plugin_test.py"
        archivo.write_text(contenido)
        return archivo

    def test_gestor_crea_directorio(self, gestor, tmp_dir):
        assert (tmp_dir / "plugins").exists()

    def test_plugin_base_ayuda(self, sentinel_mock):
        from core.PluginSystem import PluginBase

        class MiPlugin(PluginBase):
            NOMBRE = "mi_plugin"
            VERSION = "2.0"
            DESCRIPCION = "Plugin de prueba"
            AUTOR = "AutorTest"
            COMANDOS = ["cmd1"]

            def ejecutar(self, comando, args=None):
                pass

        p = MiPlugin(sentinel_mock)
        ayuda = p.ayuda()
        assert "mi_plugin" in ayuda
        assert "2.0" in ayuda
        assert "AutorTest" in ayuda
        assert "cmd1" in ayuda

    def test_plugin_base_sin_ejecutar_lanza(self, sentinel_mock):
        from core.PluginSystem import PluginBase

        class PluginIncompleto(PluginBase):
            NOMBRE = "incompleto"
            COMANDOS = []

        p = PluginIncompleto(sentinel_mock)
        with pytest.raises(NotImplementedError):
            p.ejecutar("cmd")

    def test_cargar_plugin_valido(self, gestor, plugin_archivo, sentinel_mock, monkeypatch):
        import PluginSystem as ps_mod
        monkeypatch.setattr(ps_mod, "PLUGINS_PATH",
                            str(plugin_archivo.parent))
        gestor.cargar_todos()
        assert "plugin_test" in gestor._plugins

    def test_tiene_comando(self, gestor, plugin_archivo, sentinel_mock, monkeypatch):
        import PluginSystem as ps_mod
        monkeypatch.setattr(ps_mod, "PLUGINS_PATH",
                            str(plugin_archivo.parent))
        gestor.cargar_todos()
        assert gestor.tiene_comando("test_cmd")
        assert not gestor.tiene_comando("comando_inexistente")

    def test_ejecutar_comando(self, gestor, plugin_archivo, sentinel_mock, monkeypatch):
        import PluginSystem as ps_mod
        monkeypatch.setattr(ps_mod, "PLUGINS_PATH",
                            str(plugin_archivo.parent))
        gestor.cargar_todos()
        # No debe lanzar
        gestor.ejecutar_comando("test_cmd", [])

    def test_listar_no_lanza(self, gestor):
        gestor.listar()


# ════════════════════════════════════════════════════════════════════
# TESTS — SECURITY MODULE
# ════════════════════════════════════════════════════════════════════

class TestSecurityModule:

    @pytest.fixture
    def security(self, tmp_dir, monkeypatch):
        monkeypatch.chdir(tmp_dir)
        sentinel = MagicMock()
        from core.Security import SecurityModule
        return SecurityModule(sentinel)

    def test_llave_se_crea(self, security, tmp_dir):
        assert (tmp_dir / "anubis_master.key").exists()

    def test_encriptar_archivo(self, security, tmp_dir):
        archivo = tmp_dir / "secreto.txt"
        archivo.write_text("contenido secreto")
        original = archivo.read_bytes()

        resultado = security.encriptar_archivo(str(archivo))
        assert resultado is True
        # El contenido debe haber cambiado
        assert archivo.read_bytes() != original

    def test_encriptar_y_desencriptar(self, security, tmp_dir):
        archivo = tmp_dir / "ida_y_vuelta.txt"
        texto_original = "Apex Sentinel 2.2 — datos sensibles"
        archivo.write_text(texto_original)

        security.encriptar_archivo(str(archivo))
        security.desencriptar_archivo(str(archivo))

        assert archivo.read_text() == texto_original

    def test_encriptar_archivo_inexistente(self, security):
        resultado = security.encriptar_archivo("/ruta/que/no/existe.txt")
        assert resultado is False

    def test_desencriptar_datos_invalidos(self, security, tmp_dir):
        archivo = tmp_dir / "invalido.bin"
        archivo.write_bytes(b"esto no es fernet")
        resultado = security.desencriptar_archivo(str(archivo))
        assert resultado is False

    def test_encriptar_archivo_binario(self, security, tmp_dir):
        archivo = tmp_dir / "binario.bin"
        datos = bytes(range(256))
        archivo.write_bytes(datos)

        security.encriptar_archivo(str(archivo))
        security.desencriptar_archivo(str(archivo))

        assert archivo.read_bytes() == datos


# ════════════════════════════════════════════════════════════════════
# TESTS — CVE MATCHER
# ════════════════════════════════════════════════════════════════════

class TestCVEMatcher:
    @pytest.fixture
    def cve(self, console):
        sentinel = MagicMock()
        sentinel.console = console
        sentinel.gp = None
        from modules.osint.CVEMatcher import CVEMatcher
        return CVEMatcher(sentinel)

    def test_instancia_correcta(self, cve):
        from modules.osint.CVEMatcher import CVEMatcher
        assert isinstance(cve, CVEMatcher)

    def test_severidad_colores_definidos(self):
        from modules.osint.CVEMatcher import SEVERIDAD_COLOR
        for nivel in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"]:
            assert nivel in SEVERIDAD_COLOR

    def test_severidad_emojis_definidos(self):
        from modules.osint.CVEMatcher import SEVERIDAD_EMOJI
        for nivel in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"]:
            assert nivel in SEVERIDAD_EMOJI

    def test_analizar_resultado_scan_vacio(self, cve):
        """No debe lanzar con lista vacía."""
        cve.analizar_resultado_scan([])

    def test_analizar_resultado_scan_mock(self, cve):
        """Respuesta mockeada de NVD — verifica parseo."""
        respuesta_mock = {
            "vulnerabilities": [
                {
                    "cve": {
                        "id": "CVE-2023-12345",
                        "descriptions": [
                            {"lang": "en", "value": "Test vulnerability description"}
                        ],
                        "metrics": {
                            "cvssMetricV31": [
                                {
                                    "cvssData": {
                                        "baseScore": 9.8,
                                        "baseSeverity": "CRITICAL"
                                    }
                                }
                            ]
                        }
                    }
                }
            ],
            "totalResults": 1
        }
        with patch("requests.Session.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = respuesta_mock
            # No debe lanzar
            cve.analizar_resultado_scan(
                [{"nombre": "OpenSSH", "version": "7.4"}])


# ════════════════════════════════════════════════════════════════════
# TESTS — RF MODULE (sin hardware)
# ════════════════════════════════════════════════════════════════════

class TestRFModuleIntegrado:
    @pytest.fixture
    def sentinel_mock(self, console, mock_log):
        s = MagicMock()
        s.console = console
        s.log = mock_log
        s.gp = None
        return s

    @pytest.fixture
    def rf(self, sentinel_mock, tmp_dir, monkeypatch):
        monkeypatch.chdir(tmp_dir)
        # Forzar modo mock (sin hardware)
        with patch("rf_module._RFSCANNER_OK", False):
            from modules.rf.rf_module import RFModuleIntegrado
            return RFModuleIntegrado(sentinel_mock)

    def test_instancia_sin_hardware(self, rf):
        from modules.rf.rf_module import RFModuleIntegrado
        assert isinstance(rf, RFModuleIntegrado)

    def test_identificar_banda_fm(self, rf):
        banda = rf._identificar_banda(100.0)
        # Puede venir de bands.py o de BANDAS interno
        if banda:
            assert "FM" in banda["nombre"] or "Radio" in banda["nombre"]

    def test_identificar_banda_desconocida(self, rf):
        banda = rf._identificar_banda(9999.0)
        assert banda is None

    def test_enriquecer_picos(self, rf):
        picos = [{"freq_mhz": 100.0, "potencia": -60.0, "snr_db": 15.0,
                  "bw_khz": 200.0, "piso_dbm": -75.0}]
        enriquecidos = rf._enriquecer_picos(picos)
        assert "banda" in enriquecidos[0]

    def test_estado_no_lanza(self, rf):
        rf.estado()

    def test_cerrar_no_lanza(self, rf):
        rf.cerrar()

    def test_escanear_sin_hardware_no_lanza(self, rf):
        rf.hw_disponible = False
        rf.escanear_frecuencia(433.92, duracion=1)

    def test_barrido_sin_hardware_no_lanza(self, rf):
        rf.hw_disponible = False
        rf.barrido_espectro(88.0, 108.0, 1.0)

    def test_exportar_csv_crea_archivo(self, rf, tmp_dir):
        from pathlib import Path
        rf.EXPORT_PATH = tmp_dir / "rf"
        rf.EXPORT_PATH.mkdir(parents=True, exist_ok=True)

        picos = [
            {"freq_mhz": 100.0, "potencia": -60.0, "snr_db": 15.0,
             "bw_khz": 200.0, "piso_dbm": -75.0, "mod_hint": "WFM",
             "banda": {"nombre": "FM Radio"}, "timestamp": "2025-01-01T00:00:00"}
        ]
        rf._exportar_csv(picos, 100.0)
        archivos = list(rf.EXPORT_PATH.glob("scan_*.csv"))
        assert len(archivos) == 1
        contenido = archivos[0].read_text()
        assert "freq_mhz" in contenido
        assert "100.0" in contenido

    def test_db_consultar_sin_db_no_lanza(self, rf):
        rf._db = None
        rf.db_consultar()

    def test_db_estadisticas_sin_db_no_lanza(self, rf):
        rf._db = None
        rf.db_estadisticas()


# ════════════════════════════════════════════════════════════════════
# TESTS — RFSCANNER (MotorDSP)
# ════════════════════════════════════════════════════════════════════

class TestMotorDSP:

    @pytest.fixture
    def dsp(self):
        from modules.rf.RFScanner import MotorDSP
        return MotorDSP(fft_size=2048, ventana="blackman")

    @pytest.fixture
    def iq_ruido(self):
        import numpy as np
        rng = np.random.default_rng(42)
        return (rng.standard_normal(8192) + 1j * rng.standard_normal(8192)
                ).astype(np.complex64) * 0.001

    @pytest.fixture
    def iq_tono(self):
        import numpy as np
        sr = 2_048_000
        n = 8192
        t = np.arange(n) / sr
        f = 200_000
        señal = (0.1 * np.exp(2j * np.pi * f * t)).astype(np.complex64)
        ruido = (0.001 * (np.random.randn(n) + 1j * np.random.randn(n))
                 ).astype(np.complex64)
        return señal + ruido

    def test_psd_forma_correcta(self, dsp, iq_ruido):
        import numpy as np
        freqs, psd = dsp.calcular_psd(iq_ruido, 2_048_000)
        assert len(freqs) == 2048
        assert len(psd) == 2048

    def test_psd_es_finita(self, dsp, iq_ruido):
        import numpy as np
        _, psd = dsp.calcular_psd(iq_ruido, 2_048_000)
        assert np.all(np.isfinite(psd))

    def test_piso_ruido_rango_valido(self, dsp, iq_ruido):
        _, psd = dsp.calcular_psd(iq_ruido, 2_048_000)
        piso = dsp.estimar_piso_ruido(psd)
        assert -140.0 < piso < 10.0

    def test_tono_detectado(self, dsp, iq_tono):
        freqs, psd = dsp.calcular_psd(iq_tono, 2_048_000)
        picos = dsp.detectar_picos(freqs, psd, 433.92e6, 2_048_000)
        assert len(picos) >= 1

    def test_picos_tienen_campos(self, dsp, iq_tono):
        freqs, psd = dsp.calcular_psd(iq_tono, 2_048_000)
        picos = dsp.detectar_picos(freqs, psd, 433.92e6, 2_048_000)
        if picos:
            p = picos[0]
            for campo in ["freq_mhz", "freq_hz", "potencia",
                          "snr_db", "bw_hz", "bw_khz", "piso_dbm", "timestamp"]:
                assert campo in p, f"Falta campo: {campo}"

    def test_picos_ordenados_por_snr(self, dsp, iq_tono):
        freqs, psd = dsp.calcular_psd(iq_tono, 2_048_000)
        picos = dsp.detectar_picos(freqs, psd, 433.92e6, 2_048_000)
        if len(picos) > 1:
            snrs = [p["snr_db"] for p in picos]
            assert snrs == sorted(snrs, reverse=True)

    def test_promediar_capturas(self, dsp, iq_ruido):
        import numpy as np
        _, psd1 = dsp.calcular_psd(iq_ruido, 2_048_000)
        _, psd2 = dsp.calcular_psd(iq_ruido, 2_048_000)
        promedio = dsp.promediar_capturas([psd1, psd2])
        assert len(promedio) == 2048
        assert np.all(np.isfinite(promedio))

    def test_ventanas_disponibles(self):
        from modules.rf.RFScanner import MotorDSP
        for ventana in ["blackman", "hann", "hamming"]:
            dsp = MotorDSP(fft_size=512, ventana=ventana)
            assert dsp is not None

    def test_muestras_cortas_no_lanza(self, dsp):
        import numpy as np
        iq_corto = np.ones(50, dtype=np.complex64)
        freqs, psd = dsp.calcular_psd(iq_corto, 2_048_000)
        assert len(psd) == 2048


# ════════════════════════════════════════════════════════════════════
# TESTS — HARDWARE (solo con flag --hardware)
# ════════════════════════════════════════════════════════════════════

def pytest_addoption(parser):
    parser.addoption(
        "--hardware", action="store_true", default=False,
        help="Ejecutar tests que requieren hardware SDR real conectado"
    )


@pytest.fixture
def hardware_required(request):
    if not request.config.getoption("--hardware"):
        pytest.skip("Requiere --hardware y un SDR conectado (RTL-SDR / HackRF)")


class TestRealHardware:

    def test_conectar_rtlsdr(self, hardware_required):
        from modules.rf.RFScanner import RFScanner
        sentinel = MagicMock()
        rf = RFScanner(sentinel)
        assert rf.sdr is not None, "No se pudo conectar al RTL-SDR"
        rf.cerrar()

    def test_captura_muestras_reales(self, hardware_required):
        import numpy as np
        from modules.rf.RFScanner import RFScanner
        sentinel = MagicMock()
        rf = RFScanner(sentinel)
        muestras = rf._capturar(100e6)
        assert muestras is not None
        assert len(muestras) > 0
        assert np.all(np.isfinite(muestras))
        rf.cerrar()

    def test_scan_fm_real(self, hardware_required):
        from modules.rf.RFScanner import RFScanner
        sentinel = MagicMock()
        rf = RFScanner(sentinel)
        # Escaneo de 2 segundos en FM
        rf.escanear_frecuencia(100.0, duracion=2)
        rf.cerrar()


# ════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA DIRECTO
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-q"])
