from __future__ import annotations

import importlib
import types
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from core.ModuleRegistry import MODULOS, ModuleRegistry, ModuleSpec


@pytest.fixture()
def sentinel() -> MagicMock:
    s = MagicMock()
    s.log.info = MagicMock()
    s.log.warning = MagicMock()
    s.console = MagicMock()
    return s


@pytest.fixture()
def registry(sentinel: MagicMock) -> ModuleRegistry:
    return ModuleRegistry(sentinel)


def _spec(
    attr: str = "modulo",
    cls_name: str = "MiClase",
    path: str = "paquete.modulo",
    needs_sentinel: bool = True,
    display_name: str = "",
    critico: bool = False,
) -> ModuleSpec:
    return ModuleSpec(
        attr=attr,
        cls_name=cls_name,
        module_path=path,
        needs_sentinel=needs_sentinel,
        display_name=display_name,
        critico=critico,
    )


def _fake_module(cls_name: str, cls: type | None = None) -> types.ModuleType:
    mod = types.ModuleType("fake_module")
    if cls is not None:
        setattr(mod, cls_name, cls)
    return mod


class TestModuleSpec:

    def test_display_name_hereda_cls_name_si_vacio(self):
        spec = _spec(cls_name="MiClase", display_name="")
        assert spec.display_name == "MiClase"

    def test_display_name_personalizado_no_se_sobreescribe(self):
        spec = _spec(cls_name="MiClase", display_name="NombrePersonalizado")
        assert spec.display_name == "NombrePersonalizado"

    def test_needs_sentinel_es_true_por_defecto(self):
        spec = _spec()
        assert spec.needs_sentinel is True

    def test_critico_es_false_por_defecto(self):
        spec = _spec()
        assert spec.critico is False

    def test_spec_completo_con_todos_los_campos(self):
        spec = ModuleSpec(
            attr="rf",
            cls_name="RFModule",
            module_path="modules.rf.rf_module",
            needs_sentinel=True,
            display_name="RFModuleIntegrado",
            critico=False,
        )
        assert spec.attr == "rf"
        assert spec.cls_name == "RFModule"
        assert spec.module_path == "modules.rf.rf_module"
        assert spec.display_name == "RFModuleIntegrado"

    def test_catalogo_modulos_no_esta_vacio(self):
        assert len(MODULOS) > 0

    def test_catalogo_no_tiene_attrs_duplicados(self):
        attrs = [s.attr for s in MODULOS]
        assert len(attrs) == len(
            set(attrs)), "Hay atributos duplicados en MODULOS"

    def test_catalogo_seguridad_es_critico(self):
        security = next((s for s in MODULOS if s.attr == "security"), None)
        assert security is not None
        assert security.critico is True

    def test_catalogo_rf_tiene_ruta_correcta(self):
        rf = next((s for s in MODULOS if s.attr == "rf"), None)
        assert rf is not None
        assert "rf" in rf.module_path


class TestImportar:

    def test_retorna_clase_cuando_modulo_existe(self, registry: ModuleRegistry):
        class MiClase:
            pass
        mod = _fake_module("MiClase", MiClase)
        with patch("importlib.import_module", return_value=mod):
            resultado = registry._importar("paquete.modulo", "MiClase")
        assert resultado is MiClase

    def test_retorna_none_cuando_modulo_no_existe(self, registry: ModuleRegistry):
        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            resultado = registry._importar("paquete.inexistente", "Clase")
        assert resultado is None

    def test_retorna_none_cuando_clase_no_existe_en_modulo(self, registry: ModuleRegistry):
        mod = _fake_module("OtraClase")
        with patch("importlib.import_module", return_value=mod):
            resultado = registry._importar(
                "paquete.modulo", "ClaseQueNoExiste")
        assert resultado is None

    def test_retorna_none_cuando_import_lanza_excepcion_generica(self, registry: ModuleRegistry):
        with patch("importlib.import_module", side_effect=Exception("error inesperado")):
            resultado = registry._importar("paquete.roto", "Clase")
        assert resultado is None

    def test_retorna_none_cuando_import_lanza_import_error(self, registry: ModuleRegistry):
        with patch("importlib.import_module", side_effect=ImportError("dep faltante")):
            resultado = registry._importar("paquete.sin_dep", "Clase")
        assert resultado is None


class TestCargarUno:

    def test_instancia_con_sentinel_cuando_needs_sentinel_true(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        instancias: list[Any] = []

        class MiClase:
            def __init__(self, s: Any) -> None:
                instancias.append(s)

        mod = _fake_module("MiClase", MiClase)
        spec = _spec(attr="modulo", cls_name="MiClase", needs_sentinel=True)

        with patch("importlib.import_module", return_value=mod):
            ok = registry._cargar_uno(spec)

        assert ok is True
        assert len(instancias) == 1
        assert instancias[0] is sentinel

    def test_instancia_sin_sentinel_cuando_needs_sentinel_false(
        self, registry: ModuleRegistry
    ):
        llamadas: list[int] = []

        class MiClase:
            def __init__(self) -> None:
                llamadas.append(1)

        mod = _fake_module("MiClase", MiClase)
        spec = _spec(attr="modulo", cls_name="MiClase", needs_sentinel=False)

        with patch("importlib.import_module", return_value=mod):
            ok = registry._cargar_uno(spec)

        assert ok is True
        assert len(llamadas) == 1

    def test_asigna_instancia_como_atributo_del_sentinel(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        class MiClase:
            def __init__(self, s: Any) -> None:
                pass

        mod = _fake_module("MiClase", MiClase)
        spec = _spec(attr="mi_modulo", cls_name="MiClase")

        with patch("importlib.import_module", return_value=mod):
            registry._cargar_uno(spec)

        instancia = getattr(sentinel, "mi_modulo")
        assert isinstance(instancia, MiClase)

    def test_asigna_none_y_retorna_false_si_clase_no_existe(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        mod = _fake_module("OtraClase")
        spec = _spec(attr="modulo", cls_name="ClaseAusente")

        with patch("importlib.import_module", return_value=mod):
            ok = registry._cargar_uno(spec)

        assert ok is False
        assert getattr(sentinel, "modulo") is None

    def test_asigna_none_y_retorna_false_si_init_lanza_excepcion(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        class ClaseRota:
            def __init__(self, s: Any) -> None:
                raise RuntimeError("error de inicialización")

        mod = _fake_module("ClaseRota", ClaseRota)
        spec = _spec(attr="modulo_roto", cls_name="ClaseRota")

        with patch("importlib.import_module", return_value=mod):
            ok = registry._cargar_uno(spec)

        assert ok is False
        assert getattr(sentinel, "modulo_roto") is None

    def test_asigna_none_y_retorna_false_si_modulo_no_existe(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            spec = _spec(attr="ausente", cls_name="Clase")
            ok = registry._cargar_uno(spec)

        assert ok is False
        assert getattr(sentinel, "ausente") is None

    def test_modulo_critico_falla_silenciosamente_igual(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        spec = _spec(attr="seg", cls_name="ClaseRota", critico=True)
        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            ok = registry._cargar_uno(spec)
        assert ok is False
        assert getattr(sentinel, "seg") is None

    def test_registra_warning_cuando_clase_no_existe(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        mod = _fake_module("OtraClase")
        spec = _spec(attr="modulo", cls_name="Inexistente",
                     display_name="TestModule")
        with patch("importlib.import_module", return_value=mod):
            registry._cargar_uno(spec)
        sentinel.log.warning.assert_called()

    def test_registra_warning_cuando_init_falla(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        class Rota:
            def __init__(self, s: Any) -> None:
                raise ValueError("init error")

        mod = _fake_module("Rota", Rota)
        spec = _spec(attr="roto", cls_name="Rota", display_name="RotaModule")
        with patch("importlib.import_module", return_value=mod):
            registry._cargar_uno(spec)
        sentinel.log.warning.assert_called()


class TestCargaDependencias:

    def test_recovery_retorna_false_si_security_es_none(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        sentinel.security = None
        ok = registry._cargar_recovery()
        assert ok is False
        assert getattr(sentinel, "recovery") is None

    def test_recovery_retorna_true_si_security_disponible(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        sentinel.security = MagicMock()

        class SentinelRecovery:
            def __init__(self, s: Any) -> None:
                pass

        mock_mod = _fake_module("SentinelRecovery", SentinelRecovery)
        with patch("importlib.import_module", return_value=mock_mod):
            ok = registry._cargar_recovery()

        assert ok is True
        assert getattr(sentinel, "recovery") is not None

    def test_recovery_retorna_false_si_import_falla(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):

        sentinel.security = MagicMock()
        with patch.dict("sys.modules", {"core.Recovery": None}):
            ok = registry._cargar_recovery()
        assert ok is False

    def test_motor_rep_retorna_false_si_gp_es_none(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        sentinel.gp = None
        ok = registry._cargar_motor_rep()
        assert ok is False
        assert getattr(sentinel, "motor_rep") is None

    def test_motor_rep_retorna_true_si_gp_disponible(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        sentinel.gp = MagicMock()

        class MotorReportes:
            def __init__(self, s: Any) -> None:
                pass

        mock_mod = _fake_module("MotorReportes", MotorReportes)
        with patch("importlib.import_module", return_value=mock_mod):
            ok = registry._cargar_motor_rep()

        assert ok is True

    def test_motor_rep_retorna_false_si_import_falla(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        sentinel.gp = MagicMock()
        with patch.dict("sys.modules", {"modules.reporte.MotorReportes": None}):
            ok = registry._cargar_motor_rep()
        assert ok is False


class TestCargarExtras:

    def test_evil_twin_se_asigna_si_flask_disponible(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        def iniciar_servidor(**kw: Any) -> None:
            pass

        mock_mod = _fake_module("iniciar_servidor", None)
        mock_mod.iniciar_servidor = iniciar_servidor

        with patch("importlib.import_module", return_value=mock_mod):
            registry._cargar_extras()

        assert sentinel._evil_twin_server is not None

    def test_evil_twin_es_none_si_flask_no_disponible(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        with patch.dict("sys.modules", {"modules.network.EvilTwinServer": None}):
            registry._cargar_extras()
        assert sentinel._evil_twin_server is None

    def test_scapy_primitivas_son_none_si_no_disponible(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        with patch("importlib.import_module", side_effect=ImportError):
            registry._cargar_extras()
        assert sentinel._ARP is None
        assert sentinel._Ether is None
        assert sentinel._srp is None

    def test_wa_decryptor_es_none_si_no_disponible(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        with patch("importlib.import_module", side_effect=ImportError):
            registry._cargar_extras()
        assert sentinel._wa_decryptor_cls is None


class TestEstadosYDisponible:

    def test_estados_vacio_antes_de_cargar(self, registry: ModuleRegistry):
        assert registry.estados() == {}

    def test_estados_refleja_carga_exitosa(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        class MiClase:
            def __init__(self, s: Any) -> None:
                pass

        mod = _fake_module("MiClase", MiClase)
        spec = _spec(attr="test", cls_name="MiClase",
                     display_name="TestDisplay")

        with patch("importlib.import_module", return_value=mod):
            registry._cargar_uno(spec)
            registry._resultados["test"] = (True, spec)

        estados = registry.estados()
        assert estados.get("TestDisplay") is True

    def test_estados_refleja_carga_fallida(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        spec = _spec(attr="fallido", cls_name="Clase", display_name="Fallido")
        with patch("importlib.import_module", side_effect=ImportError):
            registry._cargar_uno(spec)
            registry._resultados["fallido"] = (False, spec)

        estados = registry.estados()
        assert estados.get("Fallido") is False

    def test_disponible_true_cuando_attr_tiene_valor(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        sentinel.mi_modulo = MagicMock()
        assert registry.disponible("mi_modulo") is True

    def test_disponible_false_cuando_attr_es_none(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        sentinel.mi_modulo = None
        assert registry.disponible("mi_modulo") is False

    def test_disponible_false_cuando_attr_establecido_explicitamente_a_none(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        # MagicMock crea atributos dinámicamente para cualquier nombre,
        # por eso probamos el comportamiento real: attr = None → False
        sentinel.modulo_cargado_con_error = None
        assert registry.disponible("modulo_cargado_con_error") is False


class TestCargarTodos:

    def _mock_cargadores(self, registry: ModuleRegistry) -> None:
        registry._cargar_checker = MagicMock(return_value=True)
        registry._cargar_recovery = MagicMock(return_value=True)
        registry._cargar_motor_rep = MagicMock(return_value=True)
        registry._cargar_plugins = MagicMock(return_value=True)
        registry._cargar_extras = MagicMock()

    def test_retorna_dict_con_todos_los_modulos(
        self, registry: ModuleRegistry
    ):
        self._mock_cargadores(registry)
        with patch.object(registry, "_cargar_uno", return_value=True):
            resultado = registry.cargar_todos()
        assert isinstance(resultado, dict)
        assert len(resultado) > 0

    def test_contiene_checker_recovery_motor_rep_plugins(
        self, registry: ModuleRegistry
    ):
        self._mock_cargadores(registry)
        with patch.object(registry, "_cargar_uno", return_value=True):
            resultado = registry.cargar_todos()
        for clave in ("checker", "recovery", "motor_rep", "plugins"):
            assert clave in resultado, f"Falta '{clave}' en el resultado"

    def test_cargar_todos_llama_cargar_extras(
        self, registry: ModuleRegistry
    ):
        self._mock_cargadores(registry)
        with patch.object(registry, "_cargar_uno", return_value=True):
            registry.cargar_todos()
        registry._cargar_extras.assert_called_once()

    def test_cargar_todos_llama_checker_primero(
        self, registry: ModuleRegistry
    ):
        orden: list[str] = []
        registry._cargar_checker = MagicMock(
            side_effect=lambda: orden.append("checker") or True)
        registry._cargar_recovery = MagicMock(
            side_effect=lambda: orden.append("recovery") or True)
        registry._cargar_motor_rep = MagicMock(
            side_effect=lambda: orden.append("motor_rep") or True)
        registry._cargar_plugins = MagicMock(return_value=True)
        registry._cargar_extras = MagicMock()

        with patch.object(registry, "_cargar_uno", return_value=True):
            registry.cargar_todos()

        assert orden[0] == "checker", "checker debe cargarse primero"

    def test_cargar_todos_registra_resumen_en_log(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        self._mock_cargadores(registry)
        with patch.object(registry, "_cargar_uno", return_value=True):
            registry.cargar_todos()
        sentinel.log.info.assert_called()
        ultimo_msg = sentinel.log.info.call_args_list[-1][0][0]
        assert "Módulos cargados" in ultimo_msg

    def test_fallo_en_modulo_no_detiene_la_carga(
        self, registry: ModuleRegistry
    ):
        self._mock_cargadores(registry)
        resultados_carga: list[bool] = [False, True, True, True, False]
        contador = iter(resultados_carga)

        with patch.object(registry, "_cargar_uno", side_effect=lambda _: next(contador, True)):
            resultado = registry.cargar_todos()

        assert isinstance(resultado, dict)
        assert len(resultado) > 0

    def test_conteo_correcto_en_log(
        self, registry: ModuleRegistry, sentinel: MagicMock
    ):
        self._mock_cargadores(registry)
        n_modulos = len(MODULOS)

        with patch.object(registry, "_cargar_uno", return_value=True):
            registry.cargar_todos()

        msgs = [str(c[0][0]) for c in sentinel.log.info.call_args_list]
        resumen = next((m for m in msgs if "Módulos cargados" in m), None)
        assert resumen is not None
        assert str(n_modulos + 4) in resumen or "/" in resumen
