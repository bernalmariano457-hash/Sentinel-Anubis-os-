from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable
import time as _time
import numpy as np

try:
    from rtlsdr import RtlSdr
    _RTLSDR_OK = True
except ImportError:
    _RTLSDR_OK = False


class SDRMode(Enum):
    PSD = "psd"
    IQ = "iq"
    BOTH = "both"


@dataclass
class SDRConfig:
    center_hz:      float = 100e6
    sample_rate:    int = 2_048_000
    gain:           Any = "auto"
    ppm:            int = 0
    fft_size:       int = 2048
    mode:           SDRMode = SDRMode.PSD
    frame_interval: float = 0.25


@dataclass
class SDRFrame:
    timestamp:   float
    center_hz:   float
    sample_rate: int
    psd_dbm:     np.ndarray | None = None
    iq:          np.ndarray | None = None
    noise_floor: float = -100.0
    peak_dbm:    float = -100.0
    peak_mhz:    float = 0.0


def _sdr_worker(
    config_dict: dict,
    cmd_q: "mp.Queue",
    publisher_q: "mp.Queue",
    stop_event: Any,
    ready_event: Any,
) -> None:
    
    config = SDRConfig(**config_dict)
    sdr = None
    opened = False

    window = np.hanning(config.fft_size).astype(np.float32)
    wgain = float(np.sum(window ** 2))

    def _rebuild_window() -> None:
        nonlocal window, wgain
        window = np.hanning(config.fft_size).astype(np.float32)
        wgain = float(np.sum(window ** 2))

    def _open() -> bool:
        nonlocal sdr, opened
        if not _RTLSDR_OK:
            return False
        try:
            sdr = RtlSdr()
            sdr.sample_rate = config.sample_rate
            sdr.center_freq = config.center_hz
            sdr.gain = "auto" if config.gain == "auto" else float(config.gain)
            try:
                sdr.freq_correction = int(config.ppm)
            except Exception:
                pass
            opened = True
            ready_event.set()
            return True
        except Exception:
            sdr = None
            opened = False
            return False

    _open()

    last_tx = 0.0
    while not stop_event.is_set():
        try:
            while True:
                cmd = cmd_q.get_nowait()
                t = cmd.get("type")
                if t == "stop":
                    stop_event.set()
                    break
                if t == "tune":
                    config.center_hz = float(cmd["value"])
                    if sdr is not None:
                        sdr.center_freq = config.center_hz
                elif t == "gain":
                    config.gain = cmd["value"]
                    if sdr is not None:
                        sdr.gain = ("auto" if config.gain == "auto"
                                    else float(config.gain))
                elif t == "sample_rate":
                    config.sample_rate = int(cmd["value"])
                    if sdr is not None:
                        sdr.sample_rate = config.sample_rate
                elif t == "fft_size":
                    config.fft_size = int(cmd["value"])
                    _rebuild_window()
                elif t == "mode":
                    config.mode = SDRMode(cmd["value"])
                elif t == "interval":
                    config.frame_interval = float(cmd["value"])
                elif t == "ppm":
                    config.ppm = int(cmd["value"])
                    if sdr is not None:
                        try:
                            sdr.freq_correction = config.ppm
                        except Exception:
                            pass
                elif t == "reopen":
                    if sdr is not None:
                        try:
                            sdr.close()
                        except Exception:
                            pass
                        sdr = None
                    opened = False
                    _open()
        except queue.Empty:
            pass

        if not opened:
            time.sleep(0.5)
            _open()
            continue

        now = time.time()
        if (now - last_tx) < config.frame_interval:
            time.sleep(0.01)
            continue

        try:

            if config.mode in (SDRMode.IQ, SDRMode.BOTH):
         n = max(config.fft_size * 2, 65_536)


    else:
        n = config.fft_size * 2
    iq = sdr.read_samples(n).astype(np.complex64, copy=False)

            if iq is None or len(iq) < config.fft_size:
                time.sleep(0.05)
                continue

            frame = SDRFrame(
                timestamp=time.time(),
                center_hz=config.center_hz,
                sample_rate=config.sample_rate,
            )

            if config.mode in (SDRMode.PSD, SDRMode.BOTH):
                iq_w = iq[: config.fft_size] * window
                spec = np.fft.fftshift(np.fft.fft(iq_w))
                psd = (np.abs(spec) ** 2) / (config.sample_rate * wgain)
                pdb = (10.0 * np.log10(psd + 1e-20) + 30.0).astype(np.float32)
                frame.psd_dbm = pdb
                idx = int(np.argmax(pdb))
                frame.peak_dbm = float(pdb[idx])
                freqs = np.fft.fftshift(np.fft.fftfreq(config.fft_size,
                                                       1.0 / config.sample_rate))
                frame.peak_mhz = (config.center_hz + freqs[idx]) / 1e6
                frame.noise_floor = float(np.percentile(pdb, 15))

            if config.mode in (SDRMode.IQ, SDRMode.BOTH):
                frame.iq = iq

            try:
                publisher_q.put_nowait(frame)
            except queue.Full:
                try:
                    publisher_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    publisher_q.put_nowait(frame)
                except queue.Full:
                    pass

            last_tx = frame.timestamp

        except Exception:
            time.sleep(0.1)

    if sdr is not None:
        try:
            sdr.close()
        except Exception:
            pass


class SDRBroker:
    _instance: "SDRBroker | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "SDRBroker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = SDRBroker()
            return cls._instance

    def __init__(self) -> None:
        self._cmd_q:        "mp.Queue" = mp.Queue()
        self._publisher_q:  "mp.Queue" = mp.Queue(maxsize=8)
        self._stop_event = mp.Event()
        self._ready_event = mp.Event()
        self._worker:       mp.Process | None = None
        self._config = SDRConfig()
        self._subscribers:  list[tuple[str, "mp.Queue"]] = []
        self._sub_lock = threading.Lock()
        self._broadcast_thread: threading.Thread | None = None
        self._broadcast_stop = threading.Event()
        self._started = False
        self._is_available = _RTLSDR_OK

    def start(self, **kwargs: Any) -> None:
        if self._started:
            return
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)

        self._worker = mp.Process(
            target=_sdr_worker,
            args=(
                {
                    "center_hz":      self._config.center_hz,
                    "sample_rate":    self._config.sample_rate,
                    "gain":           self._config.gain,
                    "ppm":            self._config.ppm,
                    "fft_size":       self._config.fft_size,
                    "mode":           self._config.mode.value,
                    "frame_interval": self._config.frame_interval,
                },
                self._cmd_q,
                self._publisher_q,
                self._stop_event,
                self._ready_event,
            ),
            daemon=True,
            name="SDRBroker-Worker",
        )
        self._worker.start()

        self._broadcast_stop.clear()
        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop, daemon=True,
            name="SDRBroker-Broadcast",
        )
        self._broadcast_thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._broadcast_stop.set()
        try:
            self._cmd_q.put_nowait({"type": "stop"})
        except Exception:
            pass
        self._stop_event.set()
        if self._broadcast_thread:
            self._broadcast_thread.join(timeout=1.5)
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
            if self._worker.is_alive():
                self._worker.terminate()
        self._started = False

    def tune(self, freq_hz: float) -> None:
        self._config.center_hz = freq_hz
        self._send({"type": "tune", "value": freq_hz})

    def set_gain(self, gain: Any) -> None:
        self._config.gain = gain
        self._send({"type": "gain", "value": gain})

    def set_sample_rate(self, sr: int) -> None:
        self._config.sample_rate = sr
        self._send({"type": "sample_rate", "value": sr})

    def set_fft_size(self, n: int) -> None:
        self._config.fft_size = n
        self._send({"type": "fft_size", "value": n})

    def set_mode(self, mode: SDRMode) -> None:
        self._config.mode = mode
        self._send({"type": "mode", "value": mode.value})

    def set_frame_interval(self, seconds: float) -> None:
        self._config.frame_interval = max(0.02, float(seconds))
        self._send({"type": "interval", "value": self._config.frame_interval})

    def set_ppm(self, ppm: int) -> None:
        self._config.ppm = int(ppm)
        self._send({"type": "ppm", "value": ppm})

    def reopen(self) -> None:
        self._send({"type": "reopen"})

    def _send(self, cmd: dict) -> None:
        try:
            self._cmd_q.put_nowait(cmd)
        except Exception:
            pass

    def subscribe(self, name: str, maxsize: int = 4) -> "SDRSubscription":
        q: "mp.Queue" = mp.Queue(maxsize=maxsize)
        with self._sub_lock:
            self._subscribers.append((name, q))
        return SDRSubscription(name=name, queue=q, broker=self)

    def _unsubscribe(self, q: "mp.Queue") -> None:
        with self._sub_lock:
            self._subscribers = [(n, qq)
                                 for (n, qq) in self._subscribers if qq is not q]

    def _broadcast_loop(self) -> None:
        while not self._broadcast_stop.is_set():
            try:
                frame = self._publisher_q.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._sub_lock:
                subs = list(self._subscribers)
            for _name, q in subs:
                try:
                    q.put_nowait(frame)
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        q.put_nowait(frame)
                    except queue.Full:
                        pass

    @property
    def started(self) -> bool:
        return self._started

    @property
    def hardware_ok(self) -> bool:
        return self._is_available

    @property
    def config(self) -> SDRConfig:
        return replace(self._config)

    @property
    def subscriber_count(self) -> int:
        with self._sub_lock:
            return len(self._subscribers)


class SDRSubscription:
    def __init__(self, name: str, queue: "mp.Queue", broker: SDRBroker) -> None:
        self.name = name
        self._q = queue
        self._broker = broker
        self._closed = False
        
    def get_iq_blocking(self, min_samples: int, timeout: float = 2.0) -> "np.ndarray | None":

    buffer: list = []
    total = 0
    deadline = _time.time() + timeout
    while total < min_samples and _time.time() < deadline:
        remaining = deadline - _time.time()
        frame = self.get(timeout=max(0.05, min(remaining, 0.5)))
        if frame is None or frame.iq is None:
            continue
        buffer.append(frame.iq)
        total += len(frame.iq)
    if not buffer:
        return None
    merged = _np.concatenate(buffer) if len(buffer) > 1 else buffer[0]
    return merged[:min_samples]

    def get_latest(self) -> SDRFrame | None:
        if self._closed:
            return None
        latest: SDRFrame | None = None
        while True:
            try:
                latest = self._q.get_nowait()
            except queue.Empty:
                break
            except (EOFError, OSError):
                break
        return latest

    def get(self, timeout: float = 0.5) -> SDRFrame | None:
        if self._closed:
            return None
        try:
            return self._q.get(timeout=timeout)
        except (queue.Empty, EOFError, OSError):
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._broker._unsubscribe(self._q)
