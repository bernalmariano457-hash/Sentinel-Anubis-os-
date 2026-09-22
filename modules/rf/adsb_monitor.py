from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Optional

import numpy as np
from rich import box
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console

from adsb_decoder import (
    DEFAULT_SAMPLE_RATE_HZ,
    FlightStateRegistry,
    STALE_TIMEOUT_S,
    compass_arrow,
    demodulate_iq_to_mode_s_frames,
    icao_country_code,
    is_emergency_squawk,
)

log: logging.Logger = logging.getLogger("sentinel.rf.adsb")

try:
    from rtlsdr import RtlSdr
    _RTLSDR_OK: bool = True
except ImportError:
    RtlSdr = None
    _RTLSDR_OK = False


ADSB_CENTER_FREQ_HZ: Final[int] = 1_090_000_000
DEFAULT_GAIN_DB: Final[float] = 49.6
DEFAULT_CHUNK_SAMPLES: Final[int] = 1 << 18
QUEUE_MAXSIZE: Final[int] = 30
RENDER_REFRESH_HZ: Final[int] = 4
DEMO_FRAME_INTERVAL_S: Final[float] = 0.3
CONSUMER_POLL_TIMEOUT_S: Final[float] = 0.2
THREAD_JOIN_TIMEOUT_S: Final[float] = 2.0

ChunkKind = Literal["iq", "frame"]


@dataclass(slots=True)
class Chunk:
    kind: ChunkKind
    payload: bytes


DEMO_HEX_FRAMES: Final[tuple[str, ...]] = (
    "8D40621D58C382D690C8AC2863A7",
    "8D40621D58C386435CC412692AD6",
    "8D485020994409940838175B284F",
    "8D4840D6202CC371C32CE0576098",
)

SQUAWK_EMERGENCY_STYLES: Final[dict[str, tuple[str, str]]] = {
    "7500": ("HIJACK", "bold white on red"),
    "7600": ("RADIO", "bold yellow on dark_red"),
    "7700": ("MAYDAY", "bold white on dark_red"),
}

_ALT_COLOR_BANDS: Final[tuple[tuple[int, str], ...]] = (
    (10_000, "bright_green"),
    (18_000, "green"),
    (28_000, "yellow"),
    (36_000, "bright_yellow"),
    (99_999, "bright_cyan"),
)


def _put_drop_oldest(target_queue: "queue.Queue[Chunk]", item: Chunk) -> None:
    try:
        target_queue.put_nowait(item)
        return
    except queue.Full:
        pass
    try:
        target_queue.get_nowait()
    except queue.Empty:
        pass
    try:
        target_queue.put_nowait(item)
    except queue.Full:
        pass


def open_rtlsdr(
    center_freq_hz: int,
    sample_rate_hz: int,
    gain_db: float,
    ppm_correction: int,
    device_index: int,
) -> "RtlSdr":
    if not _RTLSDR_OK:
        raise RuntimeError("pyrtlsdr no esta instalado. Ejecuta: pip install pyrtlsdr")
    sdr = RtlSdr(device_index=device_index)
    try:
        sdr.sample_rate = sample_rate_hz
        sdr.center_freq = center_freq_hz
        sdr.gain = gain_db
        if ppm_correction:
            sdr.freq_correction = ppm_correction
    except Exception:
        sdr.close()
        raise
    return sdr


class RtlSdrProducer(threading.Thread):
    def __init__(
        self,
        sdr: "RtlSdr",
        output_queue: "queue.Queue[Chunk]",
        stop_event: threading.Event,
        chunk_samples: int = DEFAULT_CHUNK_SAMPLES,
    ) -> None:
        super().__init__(name="adsb-sdr-producer", daemon=True)
        self._sdr = sdr
        self._queue = output_queue
        self._stop_event = stop_event
        self._chunk_bytes = chunk_samples * 2
        self.error: Optional[BaseException] = None

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    raw = self._sdr.read_bytes(self._chunk_bytes)
                except Exception as exc:
                    log.error("Fallo de lectura RTL-SDR: %s", exc)
                    self.error = exc
                    self._stop_event.set()
                    break
                _put_drop_oldest(self._queue, Chunk(kind="iq", payload=bytes(raw)))
        finally:
            try:
                self._sdr.close()
            except Exception:
                pass


class DemoFrameProducer(threading.Thread):
    def __init__(
        self,
        output_queue: "queue.Queue[Chunk]",
        stop_event: threading.Event,
        interval_s: float = DEMO_FRAME_INTERVAL_S,
    ) -> None:
        super().__init__(name="adsb-demo-producer", daemon=True)
        self._queue = output_queue
        self._stop_event = stop_event
        self._interval_s = interval_s
        self.error: Optional[BaseException] = None

    def run(self) -> None:
        idx = 0
        n_frames = len(DEMO_HEX_FRAMES)
        while not self._stop_event.is_set():
            raw_frame = bytes.fromhex(DEMO_HEX_FRAMES[idx % n_frames])
            _put_drop_oldest(self._queue, Chunk(kind="frame", payload=raw_frame))
            idx += 1
            self._stop_event.wait(self._interval_s)


class ConsumerThread(threading.Thread):
    def __init__(
        self,
        input_queue: "queue.Queue[Chunk]",
        registry: FlightStateRegistry,
        registry_lock: threading.Lock,
        stop_event: threading.Event,
        sample_rate_hz: int,
    ) -> None:
        super().__init__(name="adsb-consumer", daemon=True)
        self._queue = input_queue
        self._registry = registry
        self._lock = registry_lock
        self._stop_event = stop_event
        self._sample_rate_hz = sample_rate_hz
        self.error: Optional[BaseException] = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                chunk = self._queue.get(timeout=CONSUMER_POLL_TIMEOUT_S)
            except queue.Empty:
                continue
            timestamp_s = time.monotonic()
            try:
                if chunk.kind == "iq":
                    raw_samples = np.frombuffer(chunk.payload, dtype=np.uint8)
                    raw_frames = demodulate_iq_to_mode_s_frames(raw_samples, self._sample_rate_hz)
                    if raw_frames:
                        with self._lock:
                            for raw_frame in raw_frames:
                                self._registry.ingest_raw_frame(raw_frame, timestamp_s)
                else:
                    with self._lock:
                        self._registry.ingest_raw_frame(chunk.payload, timestamp_s)
            except Exception as exc:
                log.exception("Error procesando bloque ADS-B")
                self.error = exc


def _altitude_color(altitude_ft: Optional[float]) -> str:
    if altitude_ft is None:
        return "dim white"
    for limit, color in _ALT_COLOR_BANDS:
        if altitude_ft < limit:
            return color
    return "bright_cyan"


def _format_optional(value: Optional[float], fmt: str = ".0f") -> str:
    return f"{value:{fmt}}" if value is not None else "[dim]\u00b7[/dim]"


def _format_vertical_rate(vr: Optional[float]) -> str:
    if vr is None:
        return "[dim]\u00b7[/dim]"
    sym = "\u2191" if vr > 64 else "\u2193" if vr < -64 else "\u2192"
    color = "green" if vr > 64 else "red" if vr < -64 else "dim"
    return f"[{color}]{sym}{abs(vr):.0f}[/{color}]"


def _format_squawk(squawk: Optional[str]) -> str:
    if squawk is None:
        return "[dim]\u00b7[/dim]"
    if is_emergency_squawk(squawk):
        label, style = SQUAWK_EMERGENCY_STYLES[squawk]
        return f"[{style}] {squawk} {label} [/{style}]"
    return f"[yellow]{squawk}[/yellow]"


def _format_age_bar(age_s: float, width: int = 6) -> str:
    ratio = min(1.0, age_s / STALE_TIMEOUT_S)
    filled = round(ratio * width)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    color = "green" if ratio < 0.33 else "yellow" if ratio < 0.66 else "red"
    return f"[{color}]{bar}[/{color}]"


def _build_aircraft_table(registry: FlightStateRegistry) -> Table:
    table = Table(
        show_header=True,
        header_style="bold grey82",
        border_style="grey27",
        box=box.SIMPLE_HEAD,
        row_styles=["", "on grey7"],
        expand=True,
        show_edge=False,
        padding=(0, 1),
    )
    column_defs = (
        ("", dict(width=4, no_wrap=True)),
        ("ICAO", dict(width=7, style="bold white", no_wrap=True)),
        ("CS", dict(width=8, style="bright_cyan", no_wrap=True)),
        ("Lat", dict(width=10, justify="right")),
        ("Lon", dict(width=11, justify="right")),
        ("Alt ft", dict(width=8, justify="right")),
        ("GS kt", dict(width=6, justify="right")),
        ("Hdg", dict(width=7, justify="right")),
        ("VS", dict(width=8, justify="right")),
        ("Squawk", dict(width=14, justify="center")),
        ("Dist", dict(width=7, justify="right", style="dim")),
        ("Brg", dict(width=5, justify="center", style="dim")),
        ("Msgs", dict(width=5, justify="right", style="dim")),
        ("Vida", dict(width=6, justify="center")),
    )
    for col_name, col_kw in column_defs:
        table.add_column(col_name, **col_kw)

    for ac in registry.active_aircraft():
        alt_color = _altitude_color(ac.altitude_ft)
        row_style = "on dark_red" if ac.tcas_ra_active else ("dim" if ac.age_s > 30 else "")
        dist_km = registry.distance_to_aircraft_km(ac)
        brg_deg = registry.bearing_to_aircraft_deg(ac)
        country_cc = icao_country_code(ac.icao)

        hdg_str = (
            f"{_format_optional(ac.track_deg, '.0f')} "
            f"{compass_arrow(ac.track_deg) if ac.track_deg is not None else ''}"
        )
        table.add_row(
            country_cc,
            ac.icao,
            ac.callsign or "[dim]\u00b7[/dim]",
            _format_optional(ac.latitude, "+.4f") if ac.latitude is not None else "[dim]\u00b7[/dim]",
            _format_optional(ac.longitude, "+.4f") if ac.longitude is not None else "[dim]\u00b7[/dim]",
            f"[{alt_color}]{_format_optional(ac.altitude_ft)}[/{alt_color}]",
            _format_optional(ac.groundspeed_kt),
            hdg_str,
            _format_vertical_rate(ac.vertical_rate),
            _format_squawk(ac.squawk),
            f"{dist_km:.0f}" if dist_km is not None else "[dim]\u00b7[/dim]",
            f"{compass_arrow(brg_deg)} {brg_deg:.0f}\u00b0" if brg_deg is not None else "[dim]\u00b7[/dim]",
            str(ac.msg_count),
            _format_age_bar(ac.age_s),
            style=row_style,
        )
    return table


def _build_stats_panel(registry: FlightStateRegistry) -> Panel:
    n_active = len(registry.active_aircraft())
    spark = registry.sparkline(18)
    body = Text.assemble(
        ("Aviones   ", "dim"), (f"{n_active:>4}\n", "bold bright_white"),
        ("Msgs      ", "dim"), (f"{registry.total_messages:>4}\n", "white"),
        ("Pos.      ", "dim"), (f"{registry.total_position_fixes:>4}\n", "bright_green"),
        ("Sin verif.", "dim"), (f"{registry.total_unverified_frames:>4}\n", "bright_red"),
        ("msg/s     ", "dim"), (f"{registry.messages_per_second():>4.1f}\n", "bright_yellow"),
        ("Uptime    ", "dim"), (f"{registry.session_uptime_s():>4.0f}s\n\n", "dim"),
        (spark, "bright_blue"),
    )
    return Panel(body, title="[dim]Stats[/dim]", border_style="grey27", padding=(0, 1))


def _build_tui_layout(registry: FlightStateRegistry) -> Layout:
    n_active = len(registry.active_aircraft())
    header = Text(
        f"  ADS-B  1090 MHz  {n_active} aviones  Mode S",
        style="bold white on grey15",
        justify="center",
    )
    root = Layout()
    root.split_column(Layout(name="header", size=1), Layout(name="body"))
    root["body"].split_row(
        Layout(name="table", ratio=5),
        Layout(name="stats", minimum_size=22),
    )
    root["header"].update(header)
    root["table"].update(_build_aircraft_table(registry))
    root["stats"].update(_build_stats_panel(registry))
    return root


class ADSBMonitorPipeline:
    def __init__(
        self,
        registry: FlightStateRegistry,
        console: Optional["Console"] = None,
        refresh_hz: int = RENDER_REFRESH_HZ,
    ) -> None:
        from rich.console import Console as _Console
        self.registry = registry
        self._console = console or _Console()
        self._refresh_hz = refresh_hz
        self._queue: "queue.Queue[Chunk]" = queue.Queue(maxsize=QUEUE_MAXSIZE)
        self._stop_event = threading.Event()
        self._registry_lock = threading.Lock()
        self._producer: Optional[threading.Thread] = None
        self._consumer: Optional[ConsumerThread] = None

    def run_live_sdr(
        self,
        center_freq_hz: int = ADSB_CENTER_FREQ_HZ,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        gain_db: float = DEFAULT_GAIN_DB,
        ppm_correction: int = 0,
        device_index: int = 0,
        chunk_samples: int = DEFAULT_CHUNK_SAMPLES,
    ) -> None:
        sdr = open_rtlsdr(center_freq_hz, sample_rate_hz, gain_db, ppm_correction, device_index)
        producer = RtlSdrProducer(sdr, self._queue, self._stop_event, chunk_samples)
        self._run_pipeline(producer, sample_rate_hz)
        if producer.error is not None:
            raise producer.error

    def run_demo(self, interval_s: float = DEMO_FRAME_INTERVAL_S) -> None:
        producer = DemoFrameProducer(self._queue, self._stop_event, interval_s)
        self._run_pipeline(producer, DEFAULT_SAMPLE_RATE_HZ)

    def _run_pipeline(self, producer: threading.Thread, sample_rate_hz: int) -> None:
        consumer = ConsumerThread(self._queue, self.registry, self._registry_lock, self._stop_event, sample_rate_hz)
        self._producer = producer
        self._consumer = consumer
        producer.start()
        consumer.start()

        interval_s = 1.0 / self._refresh_hz
        next_tick = time.monotonic()
        try:
            with Live(console=self._console, screen=True, auto_refresh=False) as live:
                while not self._stop_event.is_set():
                    try:
                        with self._registry_lock:
                            layout = _build_tui_layout(self.registry)
                        live.update(layout, refresh=True)
                    except Exception:
                        log.exception("Error renderizando la interfaz ADS-B")
                    next_tick += interval_s
                    sleep_for = next_tick - time.monotonic()
                    if sleep_for > 0.0:
                        time.sleep(sleep_for)
                    else:
                        next_tick = time.monotonic()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop_event.set()
        if self._producer is not None:
            self._producer.join(timeout=THREAD_JOIN_TIMEOUT_S)
        if self._consumer is not None:
            self._consumer.join(timeout=THREAD_JOIN_TIMEOUT_S)


class AircraftMonitor:
    _MODULE_LABEL: Final[str] = "ADS-B"

    def __init__(self, sentinel: object) -> None:
        self._sentinel = sentinel
        self._console: "Console" = getattr(sentinel, "console", None)
        if self._console is None:
            from rich.console import Console as _Console
            self._console = _Console()
        self._sentinel_log = getattr(sentinel, "log", None)

        rf_cfg = getattr(getattr(sentinel, "rf", None), "cfg", None)
        hw_cfg = getattr(rf_cfg, "hardware", None)
        self._gain_db: float = float(getattr(hw_cfg, "gain_db", DEFAULT_GAIN_DB))
        self._sample_rate: int = int(getattr(hw_cfg, "sample_rate", DEFAULT_SAMPLE_RATE_HZ))
        self._ppm_corr: int = int(getattr(hw_cfg, "ppm_correction", 0))
        self._device_index: int = int(getattr(hw_cfg, "device_index", 0))

        geo_ref = getattr(sentinel, "geo", None)
        pos_ref = getattr(geo_ref, "position", None)
        self._rx_lat: float = float(getattr(pos_ref, "lat", 0.0))
        self._rx_lon: float = float(getattr(pos_ref, "lon", 0.0))

    def _log_info(self, msg: str) -> None:
        self._console.print(f"[cyan][{self._MODULE_LABEL}][/cyan] {msg}")
        if self._sentinel_log:
            self._sentinel_log.info(msg, self._MODULE_LABEL)

    def _log_warn(self, msg: str) -> None:
        self._console.print(f"[yellow][!][{self._MODULE_LABEL}] {msg}[/yellow]")
        if self._sentinel_log:
            self._sentinel_log.warning(msg, self._MODULE_LABEL)

    def _log_error(self, msg: str) -> None:
        self._console.print(f"[bold red][x][{self._MODULE_LABEL}] {msg}[/bold red]")
        if self._sentinel_log:
            self._sentinel_log.error(msg, self._MODULE_LABEL)

    def menu(self) -> None:
        from rich.prompt import Prompt

        while True:
            self._console.print(Panel(
                "[1] Monitor en vivo (RTL-SDR)\n"
                "[2] Demo sin hardware\n"
                "[3] Configurar receptor (lat/lon/gain)\n"
                "[0] Volver",
                title=f"[bold cyan]{self._MODULE_LABEL}[/bold cyan]",
                border_style="cyan",
            ))
            choice = Prompt.ask(
                f"[bold cyan]{self._MODULE_LABEL}[/bold cyan]",
                choices=["0", "1", "2", "3"],
                default="2",
                console=self._console,
            )
            if choice == "0":
                break
            elif choice == "1":
                self._start_rtlsdr()
            elif choice == "2":
                self._start_demo()
            elif choice == "3":
                self._configure_receiver()

    def _start_rtlsdr(self) -> None:
        self._log_info(
            f"Iniciando captura RTL-SDR  "
            f"1090 MHz  gain={self._gain_db} dB  sr={self._sample_rate / 1e6:.1f} MSPS"
        )
        registry = FlightStateRegistry(self._rx_lat, self._rx_lon)
        pipeline = ADSBMonitorPipeline(registry, console=self._console)
        try:
            pipeline.run_live_sdr(
                center_freq_hz=ADSB_CENTER_FREQ_HZ,
                sample_rate_hz=self._sample_rate,
                gain_db=self._gain_db,
                ppm_correction=self._ppm_corr,
                device_index=self._device_index,
            )
        except Exception as exc:
            self._log_error(f"RTL-SDR no disponible: {exc}")
            self._log_warn("Iniciando modo demo como alternativa.")
            self._start_demo()

    def _start_demo(self) -> None:
        self._log_info("Modo demo ADS-B (sin hardware SDR)")
        registry = FlightStateRegistry(self._rx_lat, self._rx_lon)
        pipeline = ADSBMonitorPipeline(registry, console=self._console)
        pipeline.run_demo()

    def _configure_receiver(self) -> None:
        from rich.prompt import Prompt
        try:
            self._rx_lat = float(Prompt.ask(
                "Latitud del receptor", default=str(self._rx_lat), console=self._console
            ))
            self._rx_lon = float(Prompt.ask(
                "Longitud del receptor", default=str(self._rx_lon), console=self._console
            ))
            self._gain_db = float(Prompt.ask(
                "Ganancia RTL-SDR (dB)", default=str(self._gain_db), console=self._console
            ))
            self._log_info(
                f"Receptor configurado  "
                f"lat={self._rx_lat:.4f}  lon={self._rx_lon:.4f}  gain={self._gain_db} dB"
            )
        except ValueError as exc:
            self._log_error(f"Valor invalido: {exc}")
