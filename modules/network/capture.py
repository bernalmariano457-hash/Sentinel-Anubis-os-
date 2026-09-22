from __future__ import annotations

import queue
import signal
import threading
import time
import logging
from typing import Callable

import numpy as np

log = logging.getLogger("rfscanner.capture")

# Centinela para indicar fin de stream
_STOP_SENTINEL = None

# THREAD DE CAPTURA (productor)


class CaptureThread(threading.Thread):
    def __init__(
        self,
        sdr_manager,              # instancia de SDRManager
        sample_queue: queue.Queue,
        freq_hz:      float,
        n_muestras:   int = 524_288,
        settle_ms:    int = 50,
        reconnect_attempts: int = 5,
        reconnect_delay_s:  float = 2.0,
    ):
        super().__init__(name="rfscanner-capture", daemon=True)
        self._mgr = sdr_manager
        self._queue = sample_queue
        self._freq_hz = freq_hz
        self._n_muestras = n_muestras
        self._settle_ms = settle_ms
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay_s = reconnect_delay_s

        self._running = threading.Event()
        self._running.set()
        self._error:     Exception | None = None
        self._samples_total = 0
        self._reads_ok = 0
        self._reads_fail = 0

    def tune(self, freq_hz: float) -> None:
        self._freq_hz = freq_hz

    def stop(self) -> None:
        self._running.clear()

    @property
    def last_error(self) -> Exception | None:
        return self._error

    @property
    def stats(self) -> dict:
        return {
            "samples_total": self._samples_total,
            "reads_ok":      self._reads_ok,
            "reads_fail":    self._reads_fail,
            "queue_size":    self._queue.qsize(),
        }

    def run(self) -> None:
        log.info(f"CaptureThread iniciado — {self._freq_hz/1e6:.4f} MHz")
        fail_count = 0

        while self._running.is_set():
            try:
                samples = self._mgr.read_samples(
                    self._freq_hz,
                    self._n_muestras,
                    settle_ms=self._settle_ms,
                )
                self._samples_total += len(samples)
                self._reads_ok += 1
                fail_count = 0  # reset en éxito

                try:
                    self._queue.put_nowait(samples)
                except queue.Full:
                    # Descartar el bloque más antiguo para hacer sitio
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(samples)
                        log.debug("Queue llena — bloque antiguo descartado")
                    except queue.Empty:
                        pass

            except HardwareDisconnectedError as e:
                self._reads_fail += 1
                fail_count += 1
                log.warning(f"Hardware desconectado: {e} "
                            f"(intento {fail_count}/{self._reconnect_attempts})")

                if fail_count >= self._reconnect_attempts:
                    log.error(
                        "Máximo de intentos de reconexión alcanzado. Deteniendo captura.")
                    self._error = e
                    self._running.clear()
                    break

                # Esperar y reconectar
                time.sleep(self._reconnect_delay_s)
                try:
                    self._mgr.reconnect()
                    log.info("Reconexión exitosa")
                    fail_count = 0
                except Exception as re:
                    log.error(f"Reconexión fallida: {re}")

            except Exception as e:
                self._reads_fail += 1
                log.error(f"Error de captura inesperado: {e}", exc_info=True)
                self._error = e
                time.sleep(0.1)

        # Señal de fin al consumidor
        try:
            self._queue.put_nowait(_STOP_SENTINEL)
        except queue.Full:
            pass

        log.info(f"CaptureThread detenido — "
                 f"{self._reads_ok} lecturas OK, {self._reads_fail} errores")

# PIPELINE COMPLETO (orquestador)


class CapturePipeline:
    def __init__(self, sdr_manager, dsp_engine, queue_maxsize: int = 8):
        self._mgr = sdr_manager
        self._dsp = dsp_engine
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._capture: CaptureThread | None = None
        self._callbacks: list[Callable] = []
        self._running = False

        # Instalar manejadores de señal para graceful shutdown
        self._orig_sigint = None
        self._orig_sigterm = None

    def on_frame(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def start(
        self,
        freq_hz:    float,
        duration_s: float = 0,      # 0 = indefinido hasta stop()
        n_muestras: int = 524_288,
        gain_db:    float | None = None,
    ) -> None:

        if self._running:
            log.warning("Pipeline ya en ejecución")
            return

        if gain_db is not None:
            self._mgr.set_gain(gain_db)

        self._running = True
        self._queue = queue.Queue(maxsize=8)

        # Configurar captura
        from rfscanner.config import cfg
        self._capture = CaptureThread(
            sdr_manager=self._mgr,
            sample_queue=self._queue,
            freq_hz=freq_hz,
            n_muestras=n_muestras,
            settle_ms=cfg.scan.tune_settle_ms,
            reconnect_attempts=cfg.hardware.reconnect_attempts,
            reconnect_delay_s=cfg.hardware.reconnect_delay_s,
        )

        # Manejadores de señal para Ctrl+C limpio
        self._install_signal_handlers()

        self._capture.start()
        inicio = time.time()
        iteration = 0

        try:
            while self._running:
                # Timeout para que el bucle compruebe _running periódicamente
                try:
                    samples = self._queue.get(timeout=1.0)
                except queue.Empty:
                    if not self._capture.is_alive():
                        log.warning("CaptureThread terminó inesperadamente")
                        break
                    continue

                if samples is _STOP_SENTINEL:
                    break

                elapsed = time.time() - inicio
                if duration_s > 0 and elapsed >= duration_s:
                    self.stop()
                    break

                # DSP
                try:
                    freqs, psd = self._dsp.calcular_psd(samples)
                    picos = self._dsp.detectar_picos(freqs, psd, freq_hz)
                except Exception as e:
                    log.error(f"Error DSP: {e}", exc_info=True)
                    continue

                frame = {
                    "freqs":    freqs,
                    "psd":      psd,
                    "picos":    picos,
                    "freq_hz":  freq_hz,
                    "freq_mhz": freq_hz / 1e6,
                    "iteration": iteration,
                    "elapsed":   elapsed,
                    "capture_stats": self._capture.stats,
                }

                for cb in self._callbacks:
                    try:
                        cb(frame)
                    except Exception as e:
                        log.error(f"Error en callback: {e}", exc_info=True)

                iteration += 1

        except KeyboardInterrupt:
            log.info("Captura interrumpida por el operador")
        finally:
            self.stop()
            self._restore_signal_handlers()

    def stop(self) -> None:
        """Para la captura limpiamente."""
        self._running = False
        if self._capture and self._capture.is_alive():
            self._capture.stop()
            self._capture.join(timeout=3)
            if self._capture.is_alive():
                log.warning("CaptureThread no terminó en 3s")
        log.info("Pipeline detenida")

    def tune(self, freq_hz: float) -> None:
        if self._capture:
            self._capture.tune(freq_hz)

    def _install_signal_handlers(self) -> None:
        try:
            self._orig_sigint = signal.signal(
                signal.SIGINT,  self._handle_signal)
            self._orig_sigterm = signal.signal(
                signal.SIGTERM, self._handle_signal)
        except (OSError, ValueError):
            pass  # No disponible fuera del hilo principal

    def _restore_signal_handlers(self) -> None:
        try:
            if self._orig_sigint:
                signal.signal(signal.SIGINT,  self._orig_sigint)
            if self._orig_sigterm:
                signal.signal(signal.SIGTERM, self._orig_sigterm)
        except (OSError, ValueError):
            pass

    def _handle_signal(self, signum, frame) -> None:
        log.info(f"Señal {signum} recibida — iniciando shutdown limpio")
        self._running = False

# EXCEPCIONES


class HardwareDisconnectedError(Exception):
    """El dispositivo SDR fue desconectado del USB."""


class HardwareNotFoundError(Exception):
    """No se detectó ningún dispositivo SDR compatible."""


class HardwareConfigError(Exception):
    """Error al configurar el hardware SDR."""
