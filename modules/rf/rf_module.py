from __future__ import annotations

import logging
import re
from typing import Callable, Protocol, runtime_checkable

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich import box

from modules.rf.bands import tactical_bands
from modules.rf.rf_config import load_config, RFConfig
from modules.rf.RFScanner import RFScanner

log = logging.getLogger("sentinel.rf.module")


@runtime_checkable
class SentinelProtocol(Protocol):
    console: Console
    gp: object
    log: object


class _RichStripper:
    _TAG_PATTERN: re.Pattern = re.compile(r"\[/?[^\]]*\]")

    @classmethod
    def strip(cls, markup: str) -> str:
        return cls._TAG_PATTERN.sub("", markup)


class _ConsolePresenter:

    def __init__(self, console: Console) -> None:
        self._console = console

    def emit(self, markup: str = "") -> None:
        self._console.print(markup)

    def input(self, prompt: str) -> str:
        return self._console.input(prompt).strip()

    def panel(self, renderable: object, *, title: str, border_style: str) -> None:
        self._console.print(Panel(renderable, title=title, border_style=border_style))

    def table_in_panel(
        self,
        table: Table,
        *,
        title: str,
        border_style: str,
    ) -> None:
        self.panel(table, title=title, border_style=border_style)


class _FallbackPresenter(_ConsolePresenter):

    def emit(self, markup: str = "") -> None:
        print(_RichStripper.strip(markup))

    def input(self, prompt: str) -> str:
        return input(_RichStripper.strip(prompt)).strip()


def _build_presenter(sentinel: object) -> _ConsolePresenter:
    console = getattr(sentinel, "console", None)
    if isinstance(console, Console):
        return _ConsolePresenter(console)
    return _FallbackPresenter(Console())


class _SentinelLogger:

    def __init__(self, sentinel_log: object) -> None:
        self._log = sentinel_log

    def info(self, message: str, source: str = "RF") -> None:
        if self._log is None:
            return
        try:
            self._log.info(message, source)
        except Exception as exc:
            log.debug("_SentinelLogger.info failed silently: %s", exc)


_MOCK_DEVELOPMENT_SIGNALS: tuple[dict, ...] = (
    {"freq_offset_hz":        0, "power_dbm": -55, "mode": "nfm",  "bw_hz": 12_500},
    {"freq_offset_hz":  200_000, "power_dbm": -65, "mode": "wfm",  "bw_hz": 200_000},
    {"freq_offset_hz": -150_000, "power_dbm": -72, "mode": "am",   "bw_hz": 9_000},
    {"freq_offset_hz":  400_000, "power_dbm": -80, "mode": "tone", "bw_hz": 500},
    {"freq_offset_hz": -400_000, "power_dbm": -78, "mode": "nfm",  "bw_hz": 12_500},
)


def _is_mock_backend(scanner: RFScanner) -> bool:
    from modules.rf.rf_source import _MockBackend
    return isinstance(scanner._backend, _MockBackend)


def _populate_mock_signals(scanner: RFScanner) -> None:
    for signal_kwargs in _MOCK_DEVELOPMENT_SIGNALS:
        scanner.agregar_senal_mock(**signal_kwargs)
    log.debug("Mock development: %d synthetic signals added", len(_MOCK_DEVELOPMENT_SIGNALS))


class _TacticalBandTableBuilder:

    _COLUMNS: tuple[tuple, ...] = (
        ("Nombre",      {"min_width": 18}),
        ("Tipo",        {"min_width": 10}),
        ("Freq. min",   {"justify": "right", "min_width": 11}),
        ("Freq. max",   {"justify": "right", "min_width": 11}),
        ("Score",       {"justify": "right", "min_width": 7}),
        ("Descripción", {"style": "dim",     "min_width": 30}),
    )

    @classmethod
    def build(cls, bands: list[dict]) -> Table:
        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold red",
            show_edge=False,
            expand=True,
        )
        for column_name, column_kwargs in cls._COLUMNS:
            table.add_column(column_name, **column_kwargs)

        for band in bands:
            color = band.get("color", "red")
            table.add_row(
                f"[{color}]{band['nombre']}[/{color}]",
                band["tipo"],
                f"{band['freq_min']:.3f} MHz",
                f"{band['freq_max']:.3f} MHz",
                str(band.get("tactical_score", 0)),
                band.get("desc", ""),
            )
        return table


class _SignalDbTableBuilder:

    _COLUMNS: tuple[tuple, ...] = (
        ("Timestamp",  {"style": "dim",  "min_width": 19}),
        ("Frecuencia", {"style": "cyan", "min_width": 14}),
        ("Potencia",   {"justify": "right", "min_width": 11}),
        ("SNR",        {"justify": "right", "min_width": 8}),
        ("BW",         {"justify": "right", "min_width": 10}),
        ("Mod.",       {"min_width": 10}),
        ("Banda",      {"min_width": 16}),
    )

    @classmethod
    def build(cls, records: list[dict]) -> Table:
        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold green",
            show_edge=False,
            expand=True,
        )
        for column_name, column_kwargs in cls._COLUMNS:
            table.add_column(column_name, **column_kwargs)

        for record in records:
            table.add_row(
                record.get("timestamp", "")[:19],
                f"{record.get('freq_mhz', 0):.4f} MHz",
                f"{record.get('potencia', 0):.1f} dBm",
                f"{record.get('snr_db', 0):.1f} dB",
                f"{record.get('bw_khz', 0):.2f} kHz",
                record.get("mod_hint") or "—",
                record.get("banda") or "—",
            )
        return table


def _parse_float_input(raw: str) -> float | None:
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _parse_int_input(raw: str, default: int | None = None) -> int | None:
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


class _MenuDispatcher:

    def __init__(self, module: RFModuleIntegrado) -> None:
        self._module = module
        self._presenter = module._presenter
        self._dispatch: dict[str, Callable[[], None]] = {
            "1":  self._handle_scan_frequency,
            "2":  self._handle_spectrum_sweep,
            "3":  self._handle_known_bands_scan,
            "4":  self._handle_tactical_scan,
            "5":  self._handle_gain_config,
            "6":  self._handle_session_signals,
            "7":  self._handle_hardware_status,
            "8":  self._handle_record_iq,
            "9":  self._handle_playback_iq,
            "10": self._handle_list_recordings,
            "11": self._handle_db_query,
            "12": self._handle_db_statistics,
            "13": self._handle_active_frequencies,
            "14": self._handle_top_signals,
            "15": self._handle_tactical_bands,
            "16": self._handle_agc_toggle,
        }

    def dispatch(self, option: str) -> None:
        handler = self._dispatch.get(option)
        if handler is None:
            self._presenter.emit("[yellow][!] Opción no reconocida.[/yellow]")
            return
        handler()

    def _handle_scan_frequency(self) -> None:
        freq_raw = self._presenter.input("[bold cyan][?] Frecuencia (MHz): [/bold cyan]")
        dur_raw  = self._presenter.input("[bold cyan][?] Duración segundos [10]: [/bold cyan]")
        freq = _parse_float_input(freq_raw)
        if freq is None:
            self._presenter.emit("[red][!] Valor inválido.[/red]")
            return
        self._module.escanear_frecuencia(freq, _parse_int_input(dur_raw, default=10))

    def _handle_spectrum_sweep(self) -> None:
        ini_raw  = self._presenter.input("[bold cyan][?] Freq. inicial (MHz): [/bold cyan]")
        fin_raw  = self._presenter.input("[bold cyan][?] Freq. final (MHz): [/bold cyan]")
        paso_raw = self._presenter.input("[bold cyan][?] Paso MHz [1.0]: [/bold cyan]")
        ini  = _parse_float_input(ini_raw)
        fin  = _parse_float_input(fin_raw)
        paso = _parse_float_input(paso_raw) or 1.0
        if ini is None or fin is None:
            self._presenter.emit("[red][!] Valores inválidos.[/red]")
            return
        self._module.barrido_espectro(ini, fin, paso)

    def _handle_known_bands_scan(self) -> None:
        self._module.escaneo_bandas_conocidas()

    def _handle_tactical_scan(self) -> None:
        dur_raw = self._presenter.input("[bold cyan][?] Segundos por banda [5]: [/bold cyan]")
        self._module.escaneo_tactico(_parse_int_input(dur_raw, default=5))

    def _handle_gain_config(self) -> None:
        gan_raw = self._presenter.input("[bold cyan][?] Ganancia dB (0-80, 'auto'): [/bold cyan]")
        if gan_raw.lower() == "auto":
            self._module.configurar_ganancia("auto")
            return
        gain = _parse_float_input(gan_raw)
        if gain is None:
            self._presenter.emit("[red][!] Valor inválido.[/red]")
            return
        self._module.configurar_ganancia(gain)

    def _handle_session_signals(self) -> None:
        signals = list(self._module._scanner._senales_sesion)[-50:]
        if not signals:
            self._presenter.emit("[dim]Sin señales en esta sesión.[/dim]")
            return
        scanner = self._module._scanner
        self._presenter.emit(scanner.render.tabla_picos(signals, tracker=scanner.tracker))

    def _handle_hardware_status(self) -> None:
        self._module.estado()

    def _handle_record_iq(self) -> None:
        freq_raw = self._presenter.input("[bold cyan][?] Frecuencia a grabar (MHz): [/bold cyan]")
        dur_raw  = self._presenter.input("[bold cyan][?] Duración segundos [10]: [/bold cyan]")
        fmt_raw  = self._presenter.input("[bold cyan][?] Formato (sigmf/raw) [sigmf]: [/bold cyan]") or "sigmf"
        freq = _parse_float_input(freq_raw)
        if freq is None:
            self._presenter.emit("[red][!] Valor inválido.[/red]")
            return
        self._module.grabar_iq(freq, _parse_int_input(dur_raw, default=10), fmt_raw)

    def _handle_playback_iq(self) -> None:
        arch = self._presenter.input("[bold cyan][?] Archivo IQ (ruta): [/bold cyan]")
        modo = self._presenter.input("[bold cyan][?] Modo demod (wfm/nfm/am/usb/lsb) [wfm]: [/bold cyan]") or "wfm"
        self._module.reproducir_iq(arch, modo)

    def _handle_list_recordings(self) -> None:
        self._module.listar_grabaciones()

    def _handle_db_query(self) -> None:
        freq_raw = self._presenter.input("[bold cyan][?] Freq. mínima MHz (Enter=todas): [/bold cyan]")
        snr_raw  = self._presenter.input("[bold cyan][?] SNR mínimo dB [0]: [/bold cyan]")
        hrs_raw  = self._presenter.input("[bold cyan][?] Últimas N horas (Enter=todas): [/bold cyan]")
        self._module.db_consultar(
            freq_min=_parse_float_input(freq_raw),
            snr_min=_parse_float_input(snr_raw),
            horas=_parse_int_input(hrs_raw),
        )

    def _handle_db_statistics(self) -> None:
        self._module.db_estadisticas()

    def _handle_active_frequencies(self) -> None:
        snr_raw = self._presenter.input("[bold cyan][?] SNR mínimo dB [10]: [/bold cyan]")
        hrs_raw = self._presenter.input("[bold cyan][?] Horas hacia atrás [24]: [/bold cyan]")
        self._module.frecuencias_activas(
            snr_min=_parse_float_input(snr_raw) or 10.0,
            horas=_parse_int_input(hrs_raw, default=24),
        )

    def _handle_top_signals(self) -> None:
        n_raw = self._presenter.input("[bold cyan][?] Cuántas señales [10]: [/bold cyan]")
        self._module.top_senales(_parse_int_input(n_raw, default=10))

    def _handle_tactical_bands(self) -> None:
        self._module.bandas_tacticas()

    def _handle_agc_toggle(self) -> None:
        act_raw = self._presenter.input("[bold cyan][?] Activar AGC (s/n) [s]: [/bold cyan]").lower()
        self._module.activar_agc(act_raw != "n")


_MENU_CONTENT: str = (
    "[bold green]RF SCANNER — {hw_nombre}[/bold green]\n\n"
    " [green][1][/green]  Escanear frecuencia específica\n"
    " [green][2][/green]  Barrido de espectro (rango)\n"
    " [green][3][/green]  Escaneo de bandas conocidas\n"
    " [green][4][/green]  Escaneo táctico (progreso + resumen)\n"
    " [green][5][/green]  Ajustar ganancia\n"
    " [green][6][/green]  Ver señales de esta sesión\n"
    " [green][7][/green]  Estado del hardware\n"
    " [green][8][/green]  Grabar IQ\n"
    " [green][9][/green]  Reproducir IQ\n"
    " [green][10][/green] Listar grabaciones IQ\n"
    " [green][11][/green] Consultar base de datos RF\n"
    " [green][12][/green] Estadísticas DB\n"
    " [green][13][/green] Frecuencias activas\n"
    " [green][14][/green] Top señales\n"
    " [green][15][/green] Bandas tácticas (tabla)\n"
    " [green][16][/green] Activar / desactivar AGC"
)


class RFModuleIntegrado:

    def __init__(self, sentinel: object, config_path: str | None = None) -> None:
        self._presenter: _ConsolePresenter = _build_presenter(sentinel)
        self._sentinel_logger: _SentinelLogger = _SentinelLogger(
            getattr(sentinel, "log", None)
        )
        self.gp = getattr(sentinel, "gp", None)
        self._scanner: RFScanner = RFScanner(sentinel, config_path=config_path)
        self.cfg: RFConfig = self._scanner.cfg

        if _is_mock_backend(self._scanner):
            _populate_mock_signals(self._scanner)

        log.info("RFModuleIntegrado initialized — hw=%s", self._scanner.hw_nombre)
        self._presenter.emit(
            f"[dim][RF] Módulo listo — {self._scanner.hw_nombre}  "
            f"SR={self.cfg.hardware.sample_rate / 1e6:.3f} MHz  "
            f"FFT={self.cfg.dsp.fft_size}[/dim]"
        )

    @property
    def hw_nombre(self) -> str:
        return self._scanner.hw_nombre

    @property
    def sample_rate(self) -> int:
        return self._scanner.sample_rate

    @property
    def hw_disponible(self) -> bool:
        return self._scanner._hw_disponible

    def escanear_frecuencia(self, freq_mhz: float, duracion: int = 10) -> None:
        self._scanner.escanear_frecuencia(freq_mhz, duracion)
        self._sentinel_logger.info(
            f"Escaneo RF {freq_mhz:.3f} MHz completado ({duracion}s)"
        )

    def barrido_espectro(
        self,
        freq_ini_mhz: float,
        freq_fin_mhz: float,
        paso_mhz: float = 1.0,
    ) -> None:
        self._scanner.barrido_espectro(freq_ini_mhz, freq_fin_mhz, paso_mhz)
        self._sentinel_logger.info(
            f"Barrido RF {freq_ini_mhz:.0f}–{freq_fin_mhz:.0f} MHz completado"
        )

    def escaneo_bandas_conocidas(self) -> None:
        self._scanner.escaneo_bandas_conocidas()

    def configurar_ganancia(self, ganancia: float | str) -> None:
        self._scanner.configurar_ganancia(ganancia)

    def activar_agc(self, activar: bool = True) -> None:
        self._scanner.activar_agc(activar)
        estado = "activado" if activar else "desactivado"
        self._presenter.emit(f"[dim][RF] AGC {estado}[/dim]")
        self._sentinel_logger.info(f"AGC {estado}")

    def cargar_iq_archivo(self, path: str) -> None:
        self._scanner.cargar_iq_archivo(path)

    def agregar_senal_mock(
        self,
        freq_offset_hz: float,
        power_dbm: float = -60.0,
        mode: str = "tone",
        bw_hz: float = 12_500.0,
    ) -> None:
        self._scanner.agregar_senal_mock(freq_offset_hz, power_dbm, mode, bw_hz)

    def grabar_iq(
        self,
        freq_mhz: float,
        duracion: int = 10,
        formato: str = "sigmf",
    ) -> None:
        self._scanner.grabar_iq(freq_mhz, duracion, formato)

    def reproducir_iq(self, archivo: str, modo: str = "wfm") -> None:
        self._scanner.reproducir_iq(archivo, modo)

    def listar_grabaciones(self) -> None:
        self._scanner.recorder.listar()

    def bandas_tacticas(self) -> None:
        bands = tactical_bands()
        if not bands:
            self._presenter.emit("[dim]Sin bandas tácticas definidas.[/dim]")
            return
        table = _TacticalBandTableBuilder.build(bands)
        self._presenter.table_in_panel(
            table,
            title=f"[bold red]BANDAS TÁCTICAS  [{len(bands)}][/bold red]",
            border_style="red",
        )

    def escaneo_tactico(self, duracion_por_banda: int = 5) -> None:
        bands = tactical_bands()
        if not bands:
            self._presenter.emit("[dim]Sin bandas tácticas definidas.[/dim]")
            return

        self._presenter.emit(
            f"\n[bold red][RF] Escaneo táctico — "
            f"{len(bands)} bandas  ·  {duracion_por_banda}s c/u[/bold red]\n"
        )

        signals_before = len(self._scanner._senales_sesion)

        with Progress(
            SpinnerColumn(style="red"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=28, style="red", complete_style="bright_red"),
            TextColumn("[dim]{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self._presenter._console,
            transient=False,
        ) as progress:
            task = progress.add_task("Escaneando bandas tácticas", total=len(bands))
            for band in bands:
                freq = (band["freq_min"] + band["freq_max"]) / 2.0
                color = band.get("color", "red")
                progress.update(
                    task,
                    description=f"[{color}]{band['nombre']:<26} {freq:.3f} MHz[/{color}]",
                )
                self._scanner.escanear_frecuencia(freq, duracion_por_banda)
                progress.advance(task)

        signals_detected = len(self._scanner._senales_sesion) - signals_before
        self._presenter.emit(
            f"\n[bold red][RF] Escaneo táctico completado — "
            f"{signals_detected} señal(es) detectada(s) en {len(bands)} bandas[/bold red]"
        )
        self._sentinel_logger.info(
            f"Escaneo táctico: {len(bands)} bandas, {signals_detected} señales detectadas"
        )

    def db_consultar(
        self,
        freq_min: float | None = None,
        freq_max: float | None = None,
        snr_min: float | None = None,
        horas: int | None = None,
    ) -> None:
        try:
            records = self._scanner.db.consultar_senales(
                freq_min=freq_min,
                freq_max=freq_max,
                snr_min=snr_min,
                horas=horas,
            )
        except Exception as exc:
            log.error("db_consultar failed: %s", exc)
            self._presenter.emit(f"[red][!] Error en consulta DB: {exc}[/red]")
            return

        if not records:
            self._presenter.emit("[dim]Sin señales almacenadas con esos criterios.[/dim]")
            return

        table = _SignalDbTableBuilder.build(records)
        self._presenter.table_in_panel(
            table,
            title=f"[bold green]DB RF — {len(records)} señales[/bold green]",
            border_style="green",
        )

    def db_estadisticas(self) -> None:
        self._scanner.estadisticas_db()

    def frecuencias_activas(self, snr_min: float = 10.0, horas: int = 24) -> None:
        self._scanner.frecuencias_activas(snr_min=snr_min, horas=horas)

    def top_senales(self, n: int = 10) -> None:
        self._scanner.top_senales(n)

    def estado(self) -> None:
        self._scanner.estado()

    def menu(self) -> None:
        self._presenter.panel(
            _MENU_CONTENT.format(hw_nombre=self.hw_nombre),
            title="[bold green]RF MODULE v3.0[/bold green]",
            border_style="green",
        )
        option = self._presenter.input("[bold green][?] Opción: [/bold green]")
        _MenuDispatcher(self).dispatch(option)

    def cerrar(self) -> None:
        try:
            self._scanner.cerrar()
        except Exception as exc:
            log.warning("Error closing RFScanner: %s", exc)
        log.info("RFModuleIntegrado closed")

    def __enter__(self) -> RFModuleIntegrado:
        return self

    def __exit__(self, *_: object) -> None:
        self.cerrar()
