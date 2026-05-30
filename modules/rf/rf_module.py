from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from modules.rf.bands import tactical_bands, BANDAS_RF
from modules.rf.rf_config import load_config, RFConfig
from modules.rf.RFScanner import RFScanner

log = logging.getLogger("sentinel.rf.module")

# MÓDULO RF INTEGRADO — fachada sobre RFScanner para el sentinel

#
# Esta clase es el punto de entrada que el sentinel instancia.
# Toda la lógica de captura, DSP, renderizado, DB y grabación
# vive en RFScanner y sus submódulos. rf_module solo:
#   1. Construye RFScanner con el sentinel inyectado
#   2. Añade el mock de desarrollo con señales sintéticas por defecto
#   3. Expone la API pública que el sentinel espera
#   4. Agrega operaciones de alto nivel (bandas tácticas, consulta DB)
#      que combinan varias llamadas a RFScanner

class RFModuleIntegrado:

    def __init__(self, sentinel, config_path: str | None = None):
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        self.gp = getattr(sentinel, "gp",      None)
        self.log_s = getattr(sentinel, "log",     None)

        # El RFScanner es el núcleo — carga config, conecta hardware,
        # inicia logging, DB, DSP, Renderizador y RFRecorder
        self._scanner = RFScanner(sentinel, config_path=config_path)

        # Exponer cfg y hw_nombre directamente para accesos externos
        self.cfg:       RFConfig = self._scanner.cfg
        self.hw_nombre: str      = self._scanner.hw_nombre

        # Si el backend activo es Mock (sin SDR físico), poblar señales
        # útiles para desarrollo y demos
        from modules.rf.rf_source import _MockBackend
        if isinstance(self._scanner._backend, _MockBackend):
            self._poblar_mock_desarrollo()

        self._print(
            f"[dim][RF] Módulo listo — {self.hw_nombre}  "
            f"SR={self.cfg.hardware.sample_rate/1e6:.3f} MHz  "
            f"FFT={self.cfg.dsp.fft_size}[/dim]"
        )
        log.info("RFModuleIntegrado inicializado — hw=%s", self.hw_nombre)

    # Setup interno
    def _poblar_mock_desarrollo(self) -> None:
        senales = [
            dict(freq_offset_hz=       0, power_dbm=-55, mode="nfm",  bw_hz=12_500),
            dict(freq_offset_hz= 200_000, power_dbm=-65, mode="wfm",  bw_hz=200_000),
            dict(freq_offset_hz=-150_000, power_dbm=-72, mode="am",   bw_hz=9_000),
            dict(freq_offset_hz= 400_000, power_dbm=-80, mode="tone", bw_hz=500),
            dict(freq_offset_hz=-400_000, power_dbm=-78, mode="nfm",  bw_hz=12_500),
        ]
        for s in senales:
            self._scanner.agregar_senal_mock(**s)
        log.debug("Mock desarrollo: %d señales sintéticas añadidas", len(senales))

    # Propiedades delegadas
    @property
    def sample_rate(self) -> int:
        return self._scanner.sample_rate

    @property
    def hw_disponible(self) -> bool:
        return self._scanner._hw_disponible

    @property
    def _db(self):
        return self._scanner.db

    @property
    def _signal_db(self):
        return self._scanner.signal_db

    # API pública — delegación directa a RFScanner
    def escanear_frecuencia(self, freq_mhz: float, duracion: int = 10):
        self._sync_hw_estado()
        self._scanner.escanear_frecuencia(freq_mhz, duracion)
        self._log_sentinel(
            f"Escaneo RF {freq_mhz:.3f} MHz completado ({duracion}s)"
        )

    def barrido_espectro(self, freq_ini_mhz: float,
                         freq_fin_mhz: float, paso_mhz: float = 1.0):
        self._sync_hw_estado()
        self._scanner.barrido_espectro(freq_ini_mhz, freq_fin_mhz, paso_mhz)
        self._log_sentinel(
            f"Barrido RF {freq_ini_mhz:.0f}–{freq_fin_mhz:.0f} MHz completado"
        )

    def escaneo_bandas_conocidas(self):
        self._sync_hw_estado()
        self._scanner.escaneo_bandas_conocidas()

    def configurar_ganancia(self, ganancia):
        self._scanner.configurar_ganancia(ganancia)

    def activar_agc(self, activar: bool = True):
        self._scanner.activar_agc(activar)
        estado = "activado" if activar else "desactivado"
        self._print(f"[dim][RF] AGC {estado}[/dim]")
        self._log_sentinel(f"AGC {estado}")

    def cargar_iq_archivo(self, path: str):
        self._scanner.cargar_iq_archivo(path)
        self.hw_nombre = self._scanner.hw_nombre

    def agregar_senal_mock(self, freq_offset_hz: float,
                           power_dbm: float = -60.0,
                           mode: str = "tone",
                           bw_hz: float = 12_500.0):
        self._scanner.agregar_senal_mock(
            freq_offset_hz, power_dbm, mode, bw_hz)

    def grabar_iq(self, freq_mhz: float, duracion: int = 10,
                  formato: str = "sigmf"):
        self._sync_hw_estado()
        self._scanner.grabar_iq(freq_mhz, duracion, formato)

    def reproducir_iq(self, archivo: str, modo: str = "wfm"):
        self._scanner.reproducir_iq(archivo, modo)

    def listar_grabaciones(self):
        self._scanner.recorder.listar()

    # Operaciones de alto nivel (exclusivas de rf_module)
    def bandas_tacticas(self):
        bandas = tactical_bands()
        if not bandas:
            self._print("[dim]Sin bandas tácticas definidas.[/dim]")
            return

        tb = Table(box=box.SIMPLE_HEAD, header_style="bold red",
                   show_edge=False, expand=True)
        tb.add_column("Nombre",       min_width=18)
        tb.add_column("Tipo",         min_width=10)
        tb.add_column("Freq. min",    justify="right", min_width=11)
        tb.add_column("Freq. max",    justify="right", min_width=11)
        tb.add_column("Score",        justify="right", min_width=7)
        tb.add_column("Descripción",  style="dim",     min_width=30)

        for b in bandas:
            col = b.get("color", "red")
            tb.add_row(
                f"[{col}]{b['nombre']}[/{col}]",
                b["tipo"],
                f"{b['freq_min']:.3f} MHz",
                f"{b['freq_max']:.3f} MHz",
                str(b.get("tactical_score", 0)),
                b.get("desc", ""),
            )

        self.console.print(Panel(
            tb,
            title=f"[bold red]BANDAS TÁCTICAS  [{len(bandas)}][/bold red]",
            border_style="red",
        ))

    def escaneo_tactico(self, duracion_por_banda: int = 5):
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

        bandas = tactical_bands()
        if not bandas:
            self._print("[dim]Sin bandas tácticas definidas.[/dim]")
            return

        self._print(
            f"\n[bold red][RF] Escaneo táctico — "
            f"{len(bandas)} bandas  ·  {duracion_por_banda}s c/u[/bold red]\n"
        )

        senales_antes = len(self._scanner._senales_sesion)

        with Progress(
            SpinnerColumn(style="red"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=28, style="red", complete_style="bright_red"),
            TextColumn("[dim]{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
        ) as progress:
            tarea = progress.add_task("Escaneando bandas tácticas", total=len(bandas))

            for b in bandas:
                freq = (b["freq_min"] + b["freq_max"]) / 2.0
                col  = b.get("color", "red")
                progress.update(
                    tarea,
                    description=f"[{col}]{b['nombre']:<26} {freq:.3f} MHz[/{col}]",
                )
                self._scanner.escanear_frecuencia(freq, duracion_por_banda)
                progress.advance(tarea)

        detectadas = len(self._scanner._senales_sesion) - senales_antes
        self._print(
            f"\n[bold red][RF] Escaneo táctico completado — "
            f"{detectadas} señal(es) detectada(s) en {len(bandas)} bandas[/bold red]"
        )
        self._log_sentinel(
            f"Escaneo táctico: {len(bandas)} bandas, {detectadas} señales detectadas"
        )

    def db_consultar(self, freq_min: float | None = None,
                     freq_max: float | None = None,
                     snr_min:  float | None = None,
                     horas:    int | None = None):
        try:
            resultados = self._db.consultar_senales(
                freq_min=freq_min, freq_max=freq_max,
                snr_min=snr_min,   horas=horas,
            )
        except Exception as exc:
            self._print(f"[red][!] Error en consulta DB: {exc}[/red]")
            return

        if not resultados:
            self._print(
                "[dim]Sin señales almacenadas con esos criterios.[/dim]")
            return

        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Timestamp",  style="dim",  min_width=19)
        tb.add_column("Frecuencia", style="cyan", min_width=14)
        tb.add_column("Potencia",   justify="right", min_width=11)
        tb.add_column("SNR",        justify="right", min_width=8)
        tb.add_column("BW",         justify="right", min_width=10)
        tb.add_column("Mod.",       min_width=10)
        tb.add_column("Banda",      min_width=16)

        for r in resultados:
            tb.add_row(
                r.get("timestamp", "")[:19],
                f"{r.get('freq_mhz', 0):.4f} MHz",
                f"{r.get('potencia', 0):.1f} dBm",
                f"{r.get('snr_db', 0):.1f} dB",
                f"{r.get('bw_khz', 0):.2f} kHz",
                r.get("mod_hint") or "—",
                r.get("banda") or "—",
            )

        self.console.print(Panel(
            tb,
            title=f"[bold green]DB RF — {len(resultados)} señales[/bold green]",
            border_style="green",
        ))

    def db_estadisticas(self):
        self._scanner.estadisticas_db()

    def frecuencias_activas(self, snr_min: float = 10.0, horas: int = 24):
        self._scanner.frecuencias_activas(snr_min=snr_min, horas=horas)

    def top_senales(self, n: int = 10):
        self._scanner.top_senales(n)

    # Estado
    def estado(self):
        self._scanner.estado()

    # Menú
    def menu(self):
        self.console.print()
        self.console.print(Panel(
            f"[bold green]RF SCANNER — {self.hw_nombre}[/bold green]\n\n"
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
            " [green][16][/green] Activar / desactivar AGC",
            border_style="green",
            title="[bold green]RF MODULE v3.0[/bold green]",
        ))

        opt = self.console.input(
            "[bold green][?] Opción: [/bold green]"
        ).strip()

        if opt == "1":
            freq_s = self.console.input(
                "[bold cyan][?] Frecuencia (MHz): [/bold cyan]"
            ).strip()
            dur_s = self.console.input(
                "[bold cyan][?] Duración segundos [10]: [/bold cyan]"
            ).strip()
            try:
                self.escanear_frecuencia(
                    float(freq_s), int(dur_s) if dur_s else 10
                )
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "2":
            ini_s = self.console.input(
                "[bold cyan][?] Freq. inicial (MHz): [/bold cyan]"
            ).strip()
            fin_s = self.console.input(
                "[bold cyan][?] Freq. final (MHz): [/bold cyan]"
            ).strip()
            paso_s = self.console.input(
                "[bold cyan][?] Paso MHz [1.0]: [/bold cyan]"
            ).strip()
            try:
                self.barrido_espectro(
                    float(ini_s), float(fin_s),
                    float(paso_s) if paso_s else 1.0,
                )
            except ValueError:
                self._print("[red][!] Valores inválidos.[/red]")

        elif opt == "3":
            self.escaneo_bandas_conocidas()

        elif opt == "4":
            dur_s = self.console.input(
                "[bold cyan][?] Segundos por banda [5]: [/bold cyan]"
            ).strip()
            try:
                self.escaneo_tactico(int(dur_s) if dur_s else 5)
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "5":
            gan_s = self.console.input(
                "[bold cyan][?] Ganancia dB (0-80, 'auto'): [/bold cyan]"
            ).strip()
            try:
                self.configurar_ganancia(
                    "auto" if gan_s.lower() == "auto" else float(gan_s)
                )
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "6":
            senales = list(self._scanner._senales_sesion)[-50:]
            if senales:
                self.console.print(
                    self._scanner.render.tabla_picos(
                        senales, tracker=self._scanner.tracker
                    )
                )
            else:
                self._print("[dim]Sin señales en esta sesión.[/dim]")

        elif opt == "7":
            self.estado()

        elif opt == "8":
            freq_s = self.console.input(
                "[bold cyan][?] Frecuencia a grabar (MHz): [/bold cyan]"
            ).strip()
            dur_s = self.console.input(
                "[bold cyan][?] Duración segundos [10]: [/bold cyan]"
            ).strip()
            fmt_s = self.console.input(
                "[bold cyan][?] Formato (sigmf/raw) [sigmf]: [/bold cyan]"
            ).strip() or "sigmf"
            try:
                self.grabar_iq(float(freq_s), int(
                    dur_s) if dur_s else 10, fmt_s)
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "9":
            arch = self.console.input(
                "[bold cyan][?] Archivo IQ (ruta): [/bold cyan]"
            ).strip()
            modo = self.console.input(
                "[bold cyan][?] Modo demod (wfm/nfm/am/usb/lsb) [wfm]: [/bold cyan]"
            ).strip() or "wfm"
            self.reproducir_iq(arch, modo)

        elif opt == "10":
            self.listar_grabaciones()

        elif opt == "11":
            freq_s = self.console.input(
                "[bold cyan][?] Freq. mínima MHz (Enter=todas): [/bold cyan]"
            ).strip()
            snr_s = self.console.input(
                "[bold cyan][?] SNR mínimo dB [0]: [/bold cyan]"
            ).strip()
            hrs_s = self.console.input(
                "[bold cyan][?] Últimas N horas (Enter=todas): [/bold cyan]"
            ).strip()
            try:
                self.db_consultar(
                    freq_min=float(freq_s) if freq_s else None,
                    snr_min=float(snr_s) if snr_s else None,
                    horas=int(hrs_s) if hrs_s else None,
                )
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "12":
            self.db_estadisticas()

        elif opt == "13":
            snr_s = self.console.input(
                "[bold cyan][?] SNR mínimo dB [10]: [/bold cyan]"
            ).strip()
            hrs_s = self.console.input(
                "[bold cyan][?] Horas hacia atrás [24]: [/bold cyan]"
            ).strip()
            try:
                self.frecuencias_activas(
                    snr_min=float(snr_s) if snr_s else 10.0,
                    horas=int(hrs_s) if hrs_s else 24,
                )
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "14":
            n_s = self.console.input(
                "[bold cyan][?] Cuántas señales [10]: [/bold cyan]"
            ).strip()
            try:
                self.top_senales(int(n_s) if n_s else 10)
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "15":
            self.bandas_tacticas()

        elif opt == "16":
            act_s = self.console.input(
                "[bold cyan][?] Activar AGC (s/n) [s]: [/bold cyan]"
            ).strip().lower()
            self.activar_agc(act_s != "n")

        else:
            self._print("[yellow][!] Opción no reconocida.[/yellow]")

    # Ciclo de vida
    def cerrar(self):
        try:
            self._scanner.cerrar()
        except Exception as exc:
            log.warning("Error cerrando RFScanner: %s", exc)
        log.info("RFModuleIntegrado cerrado")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    # Helpers internos
    def _sync_hw_estado(self):
        self.hw_nombre = self._scanner.hw_nombre

    def _log_sentinel(self, msg: str):
        if self.log_s:
            try:
                self.log_s.info(msg, "RF")
            except Exception:
                pass

    def _print(self, msg: str = ""):
        if self.console:
            self.console.print(msg)
        else:
            import re
            print(re.sub(r"\[/?[^\]]*\]", "", msg))
