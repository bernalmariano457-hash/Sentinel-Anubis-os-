from __future__ import annotations

from core._base import _DomainBase
from core.validators import Validador


class RFCommands(_DomainBase):

    def rfscan(self):
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(self.console)
        if freq is not None:
            duracion = Validador.pedir_segundos(
                self.console, "[?] Duración (segundos)", 1, 300, 10)
            self.s.rf.escanear_frecuencia(freq, duracion)

    def rfmenu(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.menu()

    def rfbarrido(self):
        if not self._modulo_ok("rf"):
            return
        ini = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia inicial (MHz)")
        fin = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia final (MHz)")
        if ini is None or fin is None or ini >= fin:
            self.console.print("[red][!] Rango de frecuencias inválido.[/red]")
            return
        paso_s = self.console.input(
            "\n[bold cyan][?] Paso MHz [1.0]: [/bold cyan]").strip()
        try:
            paso = float(paso_s) if paso_s else 1.0
        except ValueError:
            paso = 1.0
        self.s.rf.barrido_espectro(ini, fin, paso)

    def rfbandas(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.escaneo_bandas_conocidas()

    def rfdb(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.db_consultar()

    def rfstats(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.db_estadisticas()

    def rfestado(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.estado()

    def radio(self):
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(self.console, "[?] Frecuencia (MHz)")
        if freq is None:
            return
        self.console.print(
            "\n[bold cyan][?] Modo de demodulación:[/bold cyan]\n"
            "  [1] WFM — Radio FM comercial (87-108 MHz)\n"
            "  [2] NFM — PMR, repetidores, emergencias\n"
            "  [3] AM  — Aviación ATC, AM broadcast\n"
            "  [4] USB — HF amateur, aeronáutico HF\n"
            "  [5] LSB — HF amateur banda baja\n"
        )
        modos = {"1": "wfm", "2": "nfm", "3": "am", "4": "usb", "5": "lsb"}
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        modo = modos.get(opt, "wfm")
        duracion = Validador.pedir_segundos(
            self.console, "[?] Duración (segundos)", 5, 300, 30)
        guardar = (self.console.input(
            "\n[bold cyan][?] ¿Guardar audio WAV? (s/N): [/bold cyan]"
        ).strip().lower() == "s")

        self.console.print(
            f"\n[bold green][RF] Sintonizando {freq:.3f} MHz · "
            f"Modo: {modo.upper()} · {duracion}s[/bold green]\n"
            "[dim]Ctrl+C para detener[/dim]\n"
        )
        try:
            import time
            import numpy as np
            from pathlib import Path
            from datetime import datetime
            from modules.rf.rf_demod import Demodulator
            from modules.rf.rf_config import DemodConfig

            cfg = DemodConfig(mode=modo, audio_rate=48000, volume=0.85)
            demod = Demodulator(cfg, sample_rate=2_048_000)
            audio_total = []
            inicio = time.time()

            while (time.time() - inicio) < duracion:
                muestras = self.s.rf._capturar(freq * 1e6)
                if muestras is None:
                    break
                audio = demod.demodulate(muestras)
                if audio is not None:
                    demod.play(audio)
                    if guardar:
                        audio_total.append(audio.copy())

            if guardar and audio_total:
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                dest = Path("data/evidence/rf") / \
                    f"audio_{freq:.3f}MHz_{modo}_{ts}.wav"
                dest.parent.mkdir(parents=True, exist_ok=True)
                demod.save_wav(np.concatenate(audio_total), str(dest))
                self.console.print(
                    f"[green][+] Audio guardado: {dest}[/green]")

            demod.stop_audio()
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Demodulación detenida.[/yellow]")
        except ImportError as e:
            self.console.print(f"[red][!] Dependencia faltante: {e}[/red]")
            self.console.print(
                "[dim]Instala: pip install scipy sounddevice --break-system-packages[/dim]")
        except Exception as e:
            self.console.print(f"[red][!] Error: {e}[/red]")

    def rfgrabar(self):
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia a grabar (MHz)")
        if freq is None:
            return
        duracion = Validador.pedir_segundos(
            self.console, "[?] Duración (segundos)", 5, 300, 10)
        try:
            from modules.rf.rf_recorder import RFRecorder
            RFRecorder(self.s).grabar(freq_mhz=freq, duracion_seg=duracion)
        except ImportError:
            self.console.print("[red][!] rf_recorder.py no encontrado.[/red]")

    def rfplay(self):
        try:
            from modules.rf.rf_recorder import RFRecorder
            rec = RFRecorder(self.s)
            rec.listar()
            archivo = self.console.input(
                "\n[bold cyan][?] Nombre del archivo: [/bold cyan]").strip()
            if not archivo:
                return
            self.console.print(
                "[bold cyan][?] Modo:[/bold cyan] [1]WFM [2]NFM [3]AM [4]USB [5]LSB")
            modos = {"1": "wfm", "2": "nfm", "3": "am", "4": "usb", "5": "lsb"}
            modo = modos.get(
                self.console.input("[bold cyan] > [/bold cyan]").strip(), "wfm")
            rec.reproducir(archivo, modo=modo)
        except ImportError:
            self.console.print("[red][!] rf_recorder.py no encontrado.[/red]")

    def noaa(self):
        # Decodificador NOAA APT — imágenes satelitales en 137 MHz
        try:
            from modules.rf.NOAADecoder import NOAADecoder
            NOAADecoder(self.s).menu()
        except ImportError as e:
            self.console.print(f"[red][!] Dependencia faltante: {e}[/red]")
            self.console.print(
                "[dim]Instala: pip install scipy Pillow --break-system-packages\n"
                "Opcional (mejor calidad): pip install apt3 --break-system-packages[/dim]"
            )
        except Exception as e:
            self.console.print(f"[red][!] Error NOAA: {e}[/red]")

    def adsb(self):
        # Monitor ADS-B — decodifica transponders de aeronaves en 1090 MHz
        duracion_s = self.console.input(
            "\n[bold cyan][?] Duración segundos (Enter = indefinido): [/bold cyan]"
        ).strip()
        duracion = int(duracion_s) if duracion_s.isdigit() else None
        try:
            from modules.rf.adsb_decoder import ADSBDecoder
            ADSBDecoder(self.s).iniciar(duracion_seg=duracion)
        except ImportError:
            self.console.print("[red][!] adsb_decoder.py no encontrado.[/red]")

    # ── Analizador de espectro RF ──────────────────────────────────────

    def spectrum(self) -> None:
        # Analizador de espectro en tiempo real con waterfall, PPM y detección
        if not self._modulo_ok("sa"):
            return
        self.s.sa.run()
