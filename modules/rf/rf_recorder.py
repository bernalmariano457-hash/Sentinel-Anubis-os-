from __future__ import annotations

import json
import logging
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn, Progress, SpinnerColumn,
    TaskProgressColumn, TimeElapsedColumn, TimeRemainingColumn,
)

log = logging.getLogger("sentinel.rf.recorder")

_IQ_DIR = Path("data/evidence/rf/iq")


class RFRecorder:

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
        formato: str = "sigmf",
    ) -> Optional[Path]:
        rf = getattr(self.sentinel, "rf_scanner", None)
        if rf is None:
            self.console.print("[red][!] rf_scanner no disponible.[/red]")
            return None

        ts    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = nombre or f"iq_{freq_mhz:.3f}MHz_{ts}"

        if formato == "sigmf":
            ruta = _IQ_DIR / f"{fname}.sigmf-data"
        else:
            ruta = _IQ_DIR / f"{fname}.iq"

        self.console.print(
            f"[bold cyan][RF] Grabando {freq_mhz:.3f} MHz · "
            f"{duracion_seg}s · {sample_rate/1e6:.2f} Msps · "
            f"fmt={formato.upper()}[/bold cyan]"
        )

        muestras_totales = []
        inicio           = time.monotonic()
        bytes_escritos   = 0

        with Progress(
            SpinnerColumn(),
            "[cyan]{task.description}[/cyan]",
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
        ) as progress:
            task = progress.add_task(
                f"Capturando {freq_mhz:.3f} MHz...",
                total=duracion_seg,
            )
            with open(ruta, "wb") as iq_file:
                while (transcurrido := time.monotonic() - inicio) < duracion_seg:
                    bloque = rf._capturar(freq_mhz * 1e6)
                    if bloque is None:
                        break
                    bloque_c64 = bloque.astype(np.complex64)
                    iq_file.write(bloque_c64.tobytes())
                    muestras_totales.append(len(bloque_c64))
                    bytes_escritos += bloque_c64.nbytes
                    progress.update(task, completed=min(transcurrido, duracion_seg))

        total_muestras = sum(muestras_totales)
        if total_muestras == 0:
            self.console.print("[red][!] No se obtuvieron muestras.[/red]")
            ruta.unlink(missing_ok=True)
            return None

        size_mb = bytes_escritos / 1e6

        meta = {
            "frecuencia_hz":   int(freq_mhz * 1e6),
            "sample_rate":     sample_rate,
            "formato":         "complex64",
            "byte_order":      "little-endian",
            "timestamp_utc":   ts,
            "duracion_seg":    duracion_seg,
            "muestras_totales": total_muestras,
            "hardware":        getattr(rf, "hw_nombre", "desconocido"),
        }

        if formato == "sigmf":
            self._escribir_meta_sigmf(ruta, meta, freq_mhz, sample_rate, ts)
        else:
            (ruta.parent / f"{fname}.json").write_text(
                json.dumps(meta, indent=4), encoding="utf-8"
            )

        self.console.print(Panel(
            f"[bold green]Grabacion completada[/bold green]\n\n"
            f"  Archivo:   [white]{ruta}[/white]\n"
            f"  Muestras:  [white]{total_muestras:,}[/white]\n"
            f"  Tamano:    [white]{size_mb:.1f} MB[/white]\n"
            f"  Duracion:  [white]{total_muestras/sample_rate:.1f}s[/white]\n\n"
            f"[dim]Compatible con: SDR# · GQRX · GNU Radio · URH · SigMF[/dim]",
            border_style="green",
        ))

        self._registrar_en_db(freq_mhz, sample_rate, total_muestras, ruta, meta)

        try:
            self.sentinel.reportes.registrar_evento(
                "RF_REC",
                f"Grabacion IQ: {freq_mhz:.3f} MHz, "
                f"{total_muestras/sample_rate:.1f}s, {size_mb:.1f}MB"
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
        from modules.rf.rf_demod import Demodulator
        from modules.rf.rf_config import DemodConfig

        ruta = Path(archivo)
        if not ruta.exists():
            self.console.print(f"[red][!] Archivo no encontrado: {ruta}[/red]")
            return

        meta_path = ruta.with_suffix(".sigmf-meta")
        if not meta_path.exists():
            meta_path = ruta.with_suffix(".json")

        if meta_path.exists():
            try:
                raw  = json.loads(meta_path.read_text())
                # SigMF usa anidamiento, fallback a formato propio
                if "global" in raw:
                    sample_rate = int(
                        raw["global"].get("core:sample_rate", sample_rate)
                    )
                    freq_hz = int(
                        raw.get("captures", [{}])[0]
                        .get("core:frequency", 0)
                    )
                else:
                    sample_rate = raw.get("sample_rate", sample_rate)
                    freq_hz     = raw.get("frecuencia_hz", 0)
                self.console.print(
                    f"[dim]Metadata: {freq_hz/1e6:.3f} MHz · "
                    f"{sample_rate/1e6:.2f} Msps[/dim]"
                )
            except Exception as e:
                log.warning("Error leyendo metadata: %s", e)

        self.console.print(
            f"[cyan][RF] Reproduciendo [bold]{ruta.name}[/bold] "
            f"en modo [bold]{modo.upper()}[/bold][/cyan]"
        )

        try:
            datos = np.fromfile(str(ruta), dtype=np.complex64)
        except Exception as e:
            self.console.print(f"[red][!] Error leyendo archivo IQ: {e}[/red]")
            return

        cfg   = DemodConfig(mode=modo, audio_rate=48000, volume=0.85)
        demod = Demodulator(cfg, sample_rate)

        bloque_size = sample_rate
        n_bloques   = len(datos) // bloque_size

        self.console.print(
            f"[dim]{len(datos):,} muestras · "
            f"{len(datos)/sample_rate:.1f}s · {n_bloques} bloques[/dim]"
        )

        for i in range(n_bloques):
            bloque = datos[i * bloque_size:(i + 1) * bloque_size]
            audio  = demod.demodulate(bloque)
            if audio is not None and len(audio) > 0:
                demod.play(audio)

        demod.stop_audio()
        self.console.print("[green][RF] Reproduccion completada.[/green]")

    def listar(self):
        archivos = sorted(
            list(_IQ_DIR.glob("*.iq")) + list(_IQ_DIR.glob("*.sigmf-data")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not archivos:
            self.console.print("[dim]No hay grabaciones IQ.[/dim]")
            return

        from rich.table import Table
        tabla = Table(
            title=f"[bold]GRABACIONES IQ[/bold] — {_IQ_DIR}",
            box=None,
            header_style="bold cyan",
        )
        tabla.add_column("Archivo",   style="white",  min_width=30)
        tabla.add_column("Tamano",    justify="right", width=9)
        tabla.add_column("Fecha",     width=20, style="dim")
        tabla.add_column("Info",      style="dim")

        for f in archivos:
            size_mb = f.stat().st_size / 1e6
            fecha   = datetime.fromtimestamp(
                f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            info    = ""

            for ext in (".sigmf-meta", ".json"):
                meta_f = f.with_suffix(ext)
                if meta_f.exists():
                    try:
                        m = json.loads(meta_f.read_text())
                        if "global" in m:
                            sr   = m["global"].get("core:sample_rate", 0)
                            freq = m.get("captures", [{}])[0].get(
                                "core:frequency", 0
                            ) / 1e6
                            dur  = m["global"].get("rfscanner:duration_s", 0)
                            hw   = m["global"].get("core:hw", "?")
                        else:
                            freq = m.get("frecuencia_hz", 0) / 1e6
                            dur  = m.get("duracion_seg", 0)
                            hw   = m.get("hardware", "?")
                        info = f"{freq:.3f}MHz · {dur}s · {hw}"
                    except Exception:
                        pass
                    break

            tabla.add_row(f.name, f"{size_mb:.1f}MB", fecha, info)

        self.console.print(tabla)

    def eliminar(self, archivo: str):
        ruta = (
            _IQ_DIR / archivo
            if not Path(archivo).is_absolute()
            else Path(archivo)
        )
        if not ruta.exists():
            self.console.print(f"[red][!] No encontrado: {archivo}[/red]")
            return
        ruta.unlink()
        for ext in (".sigmf-meta", ".json"):
            meta = ruta.with_suffix(ext)
            if meta.exists():
                meta.unlink()
        self.console.print(f"[green][+] Eliminado: {ruta.name}[/green]")

    # ── Helpers privados ───────────────────────────────────────────

    def _escribir_meta_sigmf(self, ruta: Path, meta: dict,
                              freq_mhz: float, sample_rate: int, ts: str):
        sigmf_meta = {
            "global": {
                "core:datatype":       "cf32_le",
                "core:sample_rate":    sample_rate,
                "core:version":        "1.0.0",
                "core:hw":             meta["hardware"],
                "core:description":    f"APEX SENTINEL capture @ {freq_mhz:.3f} MHz",
                "core:author":         "rfscanner",
                "core:date":           ts,
                "rfscanner:duration_s":  meta["duracion_seg"],
                "rfscanner:samples":     meta["muestras_totales"],
            },
            "captures": [{
                "core:sample_start": 0,
                "core:frequency":    int(freq_mhz * 1e6),
                "core:datetime":     ts,
            }],
            "annotations": [],
        }
        meta_path = ruta.with_suffix(".sigmf-meta")
        meta_path.write_text(
            json.dumps(sigmf_meta, indent=2), encoding="utf-8"
        )

    def _registrar_en_db(self, freq_mhz: float, sample_rate: int,
                          total_muestras: int, ruta: Path, meta: dict):
        try:
            db = getattr(
                getattr(self.sentinel, "rf_module", None), "_db", None
            )
            if db and hasattr(db, "insertar_senal"):
                pass
        except Exception:
            pass
