from __future__ import annotations

import logging
import queue
import time
from typing import Any

import numpy as np

from core.sdr_broker import SDRBroker, SDRMode, SDRFrame
from modules.rf.rf_source import SDRBackend

log = logging.getLogger("sentinel.rf.broker_backend")


class BrokerBackend(SDRBackend):

    def __init__(
        self,
        freq_hz: float = 100_000_000.0,
        sample_rate: int = 2_048_000,
        gain: float = 49.6,
        ppm: int = 0,
        device_index: int = 0,
    ) -> None:
        self._broker = SDRBroker.get()
        self._freq_hz = freq_hz
        self._sample_rate = sample_rate
        self._gain = gain

        if not self._broker.hardware_ok:
            raise RuntimeError("RTL-SDR library unavailable")

        if not self._broker.started:
            self._broker.start(
                center_hz=freq_hz,
                sample_rate=sample_rate,
                gain=gain,
                ppm=ppm,
                fft_size=2048,
                mode=SDRMode.BOTH,
                frame_interval=0.05,
            )
        else:
            self._broker.tune(freq_hz)
            self._broker.set_sample_rate(sample_rate)
            self._broker.set_gain(gain)
            self._broker.set_ppm(ppm)
            self._broker.set_mode(SDRMode.BOTH)

        self._sub = self._broker.subscribe("BrokerBackend", maxsize=6)
        self._iq_buffer: list[np.ndarray] = []
        self._iq_total = 0
        self.hw_name = (
            f"RTL-SDR(broker) sr={sample_rate/1e6:.3f} MHz "
            f"gain={gain} dB"
        )
        self._closed = False
        log.info("BrokerBackend attached: %s", self.hw_name)

    def tune(self, freq_hz: float) -> None:
        if self._closed:
            return
        self._freq_hz = freq_hz
        self._broker.tune(freq_hz)

        self._flush_iq_buffer()

    def set_gain(self, gain: Any) -> None:
        if self._closed:
            return
        self._gain = gain
        self._broker.set_gain("auto" if str(gain).lower() == "auto"
                              else float(gain))

    def read_raw(self, n_samples: int) -> np.ndarray | None:

        if self._closed:
            return None

        deadline = time.monotonic() + 3.0
        while self._iq_total < n_samples and time.monotonic() < deadline:
            frame = self._sub.get(timeout=0.5)
            if frame is None or frame.iq is None:
                continue
            self._iq_buffer.append(frame.iq)
            self._iq_total += len(frame.iq)

        if self._iq_total < n_samples:
            log.warning(
                "read_raw timeout: %d/%d muestras disponibles",
                self._iq_total, n_samples,
            )
            return None

        merged = (np.concatenate(self._iq_buffer)
                  if len(self._iq_buffer) > 1 else self._iq_buffer[0])
        out = merged[:n_samples].astype(np.complex64, copy=False)
        rest = merged[n_samples:]
        self._iq_buffer = [rest] if rest.size else []
        self._iq_total = rest.size
        return out

    def close(self) -> None:

        if self._closed:
            return
        self._closed = True
        try:
            self._sub.close()
        except Exception as exc:
            log.debug("BrokerBackend close error (ignored): %s", exc)
        log.info("BrokerBackend detached")

    def _flush_iq_buffer(self) -> None:
        self._iq_buffer = []
        self._iq_total = 0
        while True:
            try:
                self._sub.get_nowait()
            except Exception:
                break


def open_broker_backend(
    freq_hz: float = 100_000_000.0,
    sample_rate: int = 2_048_000,
    gain: float = 49.6,
    ppm: int = 0,
    device_index: int = 0,
) -> SDRBackend:
    try:
        return BrokerBackend(freq_hz, sample_rate, gain, ppm, device_index)
    except Exception as exc:
        log.warning(
            "Broker backend unavailable (%s); falling back to MockBackend",
            exc,
        )
        from modules.rf.rf_source import open_mock_backend
        return open_mock_backend(sample_rate, freq_hz)
