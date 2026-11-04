from __future__ import annotations

from rich.console import Console

from core.bootscreen import (
    _ARTE_ANUBIS_FILAS,
    _GRUPOS_MODULOS,
    MODULOS_BOOT,
    SnapshotSistema,
    _arte_anubis,
    _cuadro_boot,
    _estado_grupos,
    _gauge,
    _panel_diagnostico,
    mostrar_banner,
    mostrar_bootloader,
)
from core.ModuleRegistry import MODULOS


def _nombres_reales() -> set[str]:
    return {m.display_name for m in MODULOS}


class TestConsistenciaNombresModulos:

    def test_grupos_modulos_solo_referencia_nombres_reales(self) -> None:
        reales = _nombres_reales()
        for grupo, nombres in _GRUPOS_MODULOS.items():
            desconocidos = set(nombres) - reales
            assert not desconocidos, (
                f"grupo {grupo!r} referencia nombres que no existen en "
                f"ModuleRegistry: {desconocidos}"
            )

    def test_modulos_boot_solo_referencia_nombres_reales(self) -> None:
        reales = _nombres_reales()
        nombres = {m for m, _ in MODULOS_BOOT}
        desconocidos = nombres - reales
        assert not desconocidos, (
            f"MODULOS_BOOT referencia nombres que no existen en "
            f"ModuleRegistry: {desconocidos}"
        )

    def test_todo_modulo_real_pertenece_a_algun_grupo(self) -> None:
        reales = _nombres_reales()
        agrupados = {n for nombres in _GRUPOS_MODULOS.values()
                     for n in nombres}
        huerfanos = reales - agrupados
        assert not huerfanos, (
            f"módulos registrados que no aparecen en ningún grupo del "
            f"resumen de arranque: {huerfanos}"
        )

    def test_estado_grupos_no_pierde_grupos_con_nombres_reales(self) -> None:
        estados = {n: True for n in _nombres_reales()}
        grupos_mostrados = {g for g, _ in _estado_grupos(estados)}
        assert grupos_mostrados == set(_GRUPOS_MODULOS.keys())


class TestRenderNoFalla:

    def test_mostrar_bootloader_con_estados_reales(self) -> None:
        console = Console(width=100, record=True)
        estados = {n: True for n in _nombres_reales()}
        mostrar_bootloader(console, "Unidad-Test", "2.3.0", "wlan0", estados)
        salida = console.export_text()
        assert "UNIDAD" in salida
        assert "Unidad-Test" in salida

    def test_mostrar_banner_incluye_proyecto_activo(self) -> None:
        console = Console(width=100, record=True)
        mostrar_banner(
            console, "Unidad-Test", "2.3.0", "wlan0", proyecto="Operacion-Alpha"
        )
        salida = console.export_text()
        assert "Operacion-Alpha" in salida
        assert "Unidad-Test" in salida
        assert "wlan0" in salida

    def test_mostrar_banner_sin_proyecto_no_muestra_fila(self) -> None:
        console = Console(width=100, record=True)
        mostrar_banner(console, "Unidad-Test", "2.3.0", "wlan0")
        salida = console.export_text()
        assert "PROYECTO" not in salida

    def test_mostrar_bootloader_modo_demo_sin_estados(self) -> None:
        console = Console(width=100, record=True)
        mostrar_bootloader(console, "Demo", "2.3.0",
                           "wlan0", estados_modulos=None)
        salida = console.export_text()
        assert "30/30" in salida


class TestArteAnubis:
    def test_todas_las_filas_tienen_el_mismo_ancho(self) -> None:
        anchos = {len(izq + ojos + der)
                  for izq, ojos, der in _ARTE_ANUBIS_FILAS}
        assert len(anchos) == 1

    def test_arte_anubis_produce_texto_no_vacio(self) -> None:
        texto = _arte_anubis()
        assert len(texto.plain) > 0
        assert "◢█▙" in texto.plain


class TestDiagnostico:
    def test_gauge_clampa_valores_fuera_de_rango(self) -> None:
        bajo = _gauge("CPU", -10.0, 20)
        alto = _gauge("CPU", 150.0, 20)
        assert "-10" not in bajo
        assert "0.0%" in bajo
        assert "100.0%" in alto

    def test_panel_diagnostico_oculta_temp_si_no_hay_sensor(self) -> None:
        console = Console(width=100, record=True)
        snap = SnapshotSistema(
            cpu_pct=10.0, ram_pct=20.0, ram_usada_gb=1.0, ram_total_gb=8.0,
            disco_pct=30.0, disco_usado_gb=10.0, disco_total_gb=100.0,
            temperatura_c=None,
        )
        console.print(_panel_diagnostico(snap, compacto=False, progreso=1.0))
        salida = console.export_text()
        assert "CPU" in salida and "RAM" in salida and "DISCO" in salida
        assert "TEMP" not in salida

    def test_panel_diagnostico_muestra_temp_si_hay_sensor(self) -> None:
        console = Console(width=100, record=True)
        snap = SnapshotSistema(
            cpu_pct=10.0, ram_pct=20.0, ram_usada_gb=1.0, ram_total_gb=8.0,
            disco_pct=30.0, disco_usado_gb=10.0, disco_total_gb=100.0,
            temperatura_c=55.0,
        )
        console.print(_panel_diagnostico(snap, compacto=False, progreso=1.0))
        assert "TEMP" in console.export_text()


class TestRastroModulos:
    def test_cuadro_boot_muestra_rastro_reciente(self) -> None:
        console = Console(width=100, record=True)
        rastro = [("Mod1", True), ("Mod2", False), ("Mod3", True)]
        console.print(_cuadro_boot(4, 10, "Mod4", True, False, rastro))
        salida = console.export_text()
        assert "Mod1" in salida
        assert "Mod4" in salida

    def test_cuadro_boot_sin_rastro_no_falla(self) -> None:
        console = Console(width=100, record=True)
        console.print(_cuadro_boot(1, 10, "Mod1", True, False, None))
        assert "Mod1" in console.export_text()
