from __future__ import annotations

import logging
import struct
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

log = logging.getLogger("sentinel.rf.recorder")

_IQ_DIR = Path("data/evidence/rf/iq")


class RFRecorder:
    """
    Grabador de señales IQ para APEX SENTINEL.

    Guarda muestras IQ en formato .iq (complex64) compatible con
    SDR#, GQRX, GNU Radio y URH para análisis posterior.

    Uso:
        rec = RFRecorder(sentinel)

        # Grabar 30 segundos en 98.5 MHz
        archivo = rec.grabar(freq_mhz=98.5, duracion_seg=30)

        # Listar grabaciones
        rec.listar()

        # Reproducir (reenviar al demodulador)
        rec.reproducir(archivo, modo="wfm")
    """

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        _IQ_DIR.mkdir(parents=True, exist_ok=True)

    # ── API pública ────────────────────────────────────────────────

    def grabar(
        self,
        freq_mhz: float,
        duracion_seg: int = 10,
        sample_rate: int = 2_048_000,
        nombre: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Graba señal IQ a archivo .iq (complex64 little-endian).

        Args:
            freq_mhz:    frecuencia central en MHz
            duracion_seg: duración en segundos
            sample_rate: tasa de muestreo en Hz
            nombre:      nombre personalizado (sin extensión)

        Returns:
            Path al archivo grabado, o None si falló.
        """
        rf = getattr(self.sentinel, "rf_scanner", None)
        if rf is None:
            self.console.print("[red][!] rf_scanner no disponible.[/red]")
            return None

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fname = nombre or f"iq_{freq_mhz:.3f}MHz_{ts}"
        ruta = _IQ_DIR / f"{fname}.iq"

        # Metadata en archivo sidecar .json
        meta = {
            "frecuencia_hz":  int(freq_mhz * 1e6),
            "sample_rate":    sample_rate,
            "formato":        "complex64",
            "byte_order":     "little-endian",
            "timestamp_utc":  ts,
            "duracion_seg":   duracion_seg,
            "hardware":       getattr(rf, "hw_nombre", "desconocido"),
        }

        self.console.print(
            f"[bold cyan][RF] Grabando {freq_mhz:.3f} MHz · "
            f"{duracion_seg}s · {sample_rate/1e6:.2f} Msps[/bold cyan]"
        )

        muestras_totales = []
        inicio = time.time()

        with Progress(
            SpinnerColumn(),
            "[cyan]{task.description}[/cyan]",
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task = progress.add_task(
                f"Capturando {freq_mhz:.3f} MHz...", total=duracion_seg
            )

            while (transcurrido := time.time() - inicio) < duracion_seg:
                bloque = rf._capturar(freq_mhz * 1e6)
                if bloque is None:
                    break
                muestras_totales.append(bloque.astype(np.complex64))
                progress.update(task, completed=int(transcurrido))

        if not muestras_totales:
            self.console.print("[red][!] No se obtuvieron muestras.[/red]")
            return None

        # Concatenar y guardar
        datos = np.concatenate(muestras_totales).astype(np.complex64)
        datos.tofile(str(ruta))

        # Sidecar de metadata
        import json
        meta["muestras_totales"] = len(datos)
        (ruta.parent / f"{fname}.json").write_text(
            json.dumps(meta, indent=4), encoding="utf-8"
        )

        size_mb = ruta.stat().st_size / 1e6
        self.console.print(Panel(
            f"[bold green]✔ Grabación completada[/bold green]\n\n"
            f"  Archivo:   [white]{ruta}[/white]\n"
            f"  Muestras:  [white]{len(datos):,}[/white]\n"
            f"  Tamaño:    [white]{size_mb:.1f} MB[/white]\n"
            f"  Duración:  [white]{len(datos)/sample_rate:.1f}s[/white]\n\n"
            f"[dim]Compatible con: SDR# · GQRX · GNU Radio · URH[/dim]",
            border_style="green",
        ))

        # Log en Sentinel
        try:
            self.sentinel.reportes.registrar_evento(
                "RF_REC",
                f"Grabación IQ: {freq_mhz:.3f} MHz, "
                f"{len(datos)/sample_rate:.1f}s, {size_mb:.1f}MB → {ruta.name}"
            )
        except Exception:
            pass

        return ruta

    def reproducir(
        self,
        archivo: str | Path,
        modo: str = "wfm",
        sample_rate: int = 2_048_000,
    ):
        """
        Carga un archivo .iq grabado y lo pasa por el demodulador.

        Args:
            archivo:     ruta al archivo .iq
            modo:        wfm | nfm | am | usb | lsb
            sample_rate: debe coincidir con la grabación original
        """
        from modules.rf.rf_demod import Demodulator
        from modules.rf.rf_config import DemodConfig

        ruta = Path(archivo)
        if not ruta.exists():
            self.console.print(f"[red][!] Archivo no encontrado: {ruta}[/red]")
            return

        # Intentar leer metadata
        meta_path = ruta.with_suffix(".json")
        if meta_path.exists():
            import json
            meta = json.loads(meta_path.read_text())
            sample_rate = meta.get("sample_rate", sample_rate)
            freq_hz = meta.get("frecuencia_hz", 0)
            self.console.print(
                f"[dim]Metadata: {freq_hz/1e6:.3f} MHz · "
                f"{sample_rate/1e6:.2f} Msps[/dim]"
            )

        self.console.print(
            f"[cyan][RF] Reproduciendo [bold]{ruta.name}[/bold] "
            f"en modo [bold]{modo.upper()}[/bold][/cyan]"
        )

        try:
            datos = np.fromfile(str(ruta), dtype=np.complex64)
        except Exception as e:
            self.console.print(f"[red][!] Error leyendo archivo IQ: {e}[/red]")
            return

        cfg = DemodConfig(mode=modo, audio_rate=48000, volume=0.85)
        demod = Demodulator(cfg, sample_rate)

        # Procesar en bloques para evitar picos de memoria
        bloque_size = sample_rate   # 1 segundo por bloque
        n_bloques = len(datos) // bloque_size

        self.console.print(
            f"[dim]{len(datos):,} muestras · {len(datos)/sample_rate:.1f}s · "
            f"{n_bloques} bloques[/dim]"
        )

        for i in range(n_bloques):
            bloque = datos[i * bloque_size:(i + 1) * bloque_size]
            audio = demod.demodulate(bloque)
            if audio is not None and len(audio) > 0:
                demod.play(audio)

        demod.stop_audio()
        self.console.print("[green][RF] Reproducción completada.[/green]")

    def listar(self):
        """Lista todas las grabaciones IQ disponibles."""
        archivos = sorted(_IQ_DIR.glob("*.iq"),
                          key=lambda f: f.stat().st_mtime, reverse=True)

        if not archivos:
            self.console.print("[dim]No hay grabaciones IQ.[/dim]")
            return

        from rich.table import Table
        tabla = Table(
            title=f"[bold]GRABACIONES IQ[/bold] — {_IQ_DIR}",
            box=None,
            header_style="bold cyan",
        )
        tabla.add_column("Archivo",    style="white",  min_width=30)
        tabla.add_column("Tamaño",     justify="right", width=9)
        tabla.add_column("Fecha",      width=20, style="dim")
        tabla.add_column("Info",       style="dim")

        import json
        for f in archivos:
            size_mb = f.stat().st_size / 1e6
            fecha = datetime.fromtimestamp(
                f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            info = ""
            meta_f = f.with_suffix(".json")
            if meta_f.exists():
                try:
                    m = json.loads(meta_f.read_text())
                    freq = m.get("frecuencia_hz", 0) / 1e6
                    dur = m.get("duracion_seg", 0)
                    hw = m.get("hardware", "?")
                    info = f"{freq:.3f}MHz · {dur}s · {hw}"
                except Exception:
                    pass
            tabla.add_row(f.name, f"{size_mb:.1f}MB", fecha, info)

        self.console.print(tabla)

    def eliminar(self, archivo: str):
        """Elimina una grabación IQ y su metadata."""
        ruta = _IQ_DIR / \
            archivo if not Path(archivo).is_absolute() else Path(archivo)
        if not ruta.exists():
            self.console.print(f"[red][!] No encontrado: {archivo}[/red]")
            return
        ruta.unlink()
        meta = ruta.with_suffix(".json")
        if meta.exists():
            meta.unlink()
        self.console.print(f"[green][+] Eliminado: {ruta.name}[/green]")
