from __future__ import annotations

import logging
import socket
import struct
import threading
import weakref
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Final

import numpy as np

log = logging.getLogger(__name__)

Source = Callable[[], bytes | None]
SourceFactory = Callable[[float, int], Source]

_IQ_SCALE: Final[float] = 1.0 / 127.5
_U8_OFFSET: Final[float] = 127.5
_TCP_MAGIC_HEADER_BYTES: Final[int] = 12
_TCP_CMD_PACK_FORMAT: Final[str] = ">BI"
_TCP_CMD_FREQ: Final[int] = 0x01
_TCP_CMD_SAMPLE_RATE: Final[int] = 0x02
_TCP_CMD_GAIN_MODE: Final[int] = 0x03
_TCP_CMD_GAIN: Final[int] = 0x04
_TCP_CMD_MANUAL_GAIN_MODE: Final[int] = 1
_TCP_RECV_CHUNK_BYTES: Final[int] = 65_536
_TCP_MAX_BUFFER_BYTES: Final[int] = 4 * 1024 * 1024
_TCP_GAIN_AUTO_TAG: Final[str] = "auto"
_TCP_GAIN_SCALE: Final[float] = 10.0
_FILE_READ_ALIGNMENT: Final[int] = 2


_registry_lock: threading.Lock = threading.Lock()
_active_backends: weakref.WeakSet[SDRBackend] = weakref.WeakSet()


def _register_backend(backend: SDRBackend) -> None:
    with _registry_lock:
        _active_backends.add(backend)


def close_all_backends() -> None:
    with _registry_lock:
        targets = list(_active_backends)
    for backend in targets:
        try:
            backend.close()
        except Exception as exc:
            log.warning("Backend close error during global cleanup: %s", exc)


def _u8_to_cf32(raw: bytes) -> np.ndarray:
    arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    scaled = arr * _IQ_SCALE - 1.0
    return scaled[0::2] + 1j * scaled[1::2]


def _cf32_to_u8(iq: np.ndarray) -> bytes:
    real_u8 = (np.real(iq) * _U8_OFFSET + _U8_OFFSET).clip(0, 255).astype(np.uint8)
    imag_u8 = (np.imag(iq) * _U8_OFFSET + _U8_OFFSET).clip(0, 255).astype(np.uint8)
    return np.stack((real_u8, imag_u8), axis=1).ravel().tobytes()


GainValue = float | str


class SDRBackend(ABC):

    hw_name: str = "Unknown"

    @abstractmethod
    def read_raw(self, n_samples: int) -> np.ndarray | None: ...

    @abstractmethod
    def tune(self, freq_hz: float) -> None: ...

    @abstractmethod
    def set_gain(self, gain: GainValue) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def as_source(self, sample_rate: int) -> Source:
        chunk_size = sample_rate // 10

        def _read() -> bytes | None:
            iq = self.read_raw(chunk_size)
            return None if iq is None else _cf32_to_u8(iq)

        return _read

    def __enter__(self) -> SDRBackend:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()


class _RTLSDRBackend(SDRBackend):

    def __init__(
        self,
        freq_hz: float,
        sample_rate: int,
        gain: float,
        ppm: int,
        device_index: int,
    ) -> None:
        try:
            from rtlsdr import RtlSdr
        except ImportError as exc:
            raise ImportError(
                "pyrtlsdr not installed: pip install pyrtlsdr --break-system-packages"
            ) from exc

        sdr = RtlSdr(device_index=device_index)
        sdr.sample_rate = sample_rate
        sdr.center_freq = int(freq_hz)
        sdr.gain = gain
        sdr.freq_correction = ppm
        self._sdr = sdr
        self._sample_rate = sample_rate
        self.hw_name = (
            f"RTL-SDR idx={device_index} "
            f"sr={sample_rate / 1e6:.3f} MHz gain={gain} dB"
        )
        _register_backend(self)
        log.info("RTL-SDR opened: %s", self.hw_name)

    def read_raw(self, n_samples: int) -> np.ndarray | None:
        try:
            return np.array(self._sdr.read_samples(n_samples), dtype=np.complex64)
        except Exception as exc:
            log.warning("RTL-SDR read_raw failed: %s", exc)
            return None

    def tune(self, freq_hz: float) -> None:
        self._sdr.center_freq = int(freq_hz)

    def set_gain(self, gain: GainValue) -> None:
        self._sdr.gain = gain

    def close(self) -> None:
        try:
            self._sdr.close()
        except Exception as exc:
            log.debug("RTL-SDR close error (ignored): %s", exc)


class _TCPBackend(SDRBackend):

    def __init__(
        self,
        host: str,
        port: int,
        freq_hz: float,
        sample_rate: int,
        gain: int,
    ) -> None:
        self._host = host
        self._port = port
        self._sample_rate = sample_rate
        self._gain = gain
        self._sock: socket.socket | None = None
        self._buf: bytearray = bytearray()
        self._lock: threading.Lock = threading.Lock()
        self.hw_name = f"rtl_tcp://{host}:{port} sr={sample_rate / 1e6:.3f} MHz"
        self._connect(freq_hz)
        _register_backend(self)
        log.info("TCP backend connected: %s", self.hw_name)

    @staticmethod
    def _send_cmd(sock: socket.socket, cmd: int, param: int) -> None:
        sock.sendall(struct.pack(_TCP_CMD_PACK_FORMAT, cmd, param))

    def _connect(self, freq_hz: float) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            sock.connect((self._host, self._port))
            sock.settimeout(5.0)
            sock.recv(_TCP_MAGIC_HEADER_BYTES)
            self._send_cmd(sock, _TCP_CMD_FREQ, int(freq_hz))
            self._send_cmd(sock, _TCP_CMD_SAMPLE_RATE, self._sample_rate)
            self._send_cmd(sock, _TCP_CMD_GAIN, self._gain)
            self._send_cmd(sock, _TCP_CMD_GAIN_MODE, _TCP_CMD_MANUAL_GAIN_MODE)
        except Exception:
            sock.close()
            raise
        self._sock = sock
        self._current_freq_hz = freq_hz

    def read_raw(self, n_samples: int) -> np.ndarray | None:
        needed_bytes = n_samples * _FILE_READ_ALIGNMENT
        with self._lock:
            if self._sock is None:
                return None
            while len(self._buf) < needed_bytes:
                if len(self._buf) > _TCP_MAX_BUFFER_BYTES:
                    log.error(
                        "TCP buffer overflow (%d bytes); connection reset",
                        len(self._buf),
                    )
                    self._buf.clear()
                    return None
                try:
                    chunk = self._sock.recv(_TCP_RECV_CHUNK_BYTES)
                    if not chunk:
                        return None
                    self._buf.extend(chunk)
                except socket.timeout:
                    break
            if len(self._buf) < needed_bytes:
                return None
            raw = bytes(self._buf[:needed_bytes])
            del self._buf[:needed_bytes]
        return _u8_to_cf32(raw)

    def tune(self, freq_hz: float) -> None:
        with self._lock:
            if self._sock is None:
                return
            try:
                self._send_cmd(self._sock, _TCP_CMD_FREQ, int(freq_hz))
                self._current_freq_hz = freq_hz
            except Exception as exc:
                log.warning(
                    "TCP tune to %.3f MHz failed (%s); reconnecting",
                    freq_hz / 1e6,
                    exc,
                )
                self._sock = None
                self._buf.clear()
                try:
                    self._connect(freq_hz)
                except Exception as reconnect_exc:
                    log.error("TCP reconnect failed: %s", reconnect_exc)

    def set_gain(self, gain: GainValue) -> None:
        with self._lock:
            if self._sock is None:
                return
            try:
                raw_gain = (
                    0
                    if str(gain).lower() == _TCP_GAIN_AUTO_TAG
                    else int(float(gain) * _TCP_GAIN_SCALE)
                )
                self._send_cmd(self._sock, _TCP_CMD_GAIN, raw_gain)
            except Exception as exc:
                log.warning("TCP set_gain failed: %s", exc)

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception as exc:
                    log.debug("TCP socket close error (ignored): %s", exc)
                finally:
                    self._sock = None


class _FileBackend(SDRBackend):

    def __init__(self, path: str, loop: bool = True) -> None:
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"IQ file not found: {resolved}")
        self._fh = resolved.open("rb")
        self._loop = loop
        self.hw_name = f"FILE:{resolved.name}"
        _register_backend(self)
        log.info("File backend opened: %s", self.hw_name)

    def read_raw(self, n_samples: int) -> np.ndarray | None:
        needed = n_samples * _FILE_READ_ALIGNMENT
        data = self._fh.read(needed)
        if not data:
            if not self._loop:
                return None
            self._fh.seek(0)
            data = self._fh.read(needed)
        if not data:
            return None
        aligned = data if len(data) % _FILE_READ_ALIGNMENT == 0 else data[:-1]
        return _u8_to_cf32(aligned)

    def tune(self, freq_hz: float) -> None:
        pass

    def set_gain(self, gain: GainValue) -> None:
        pass

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception as exc:
            log.debug("File backend close error (ignored): %s", exc)


_MockSignalSpec = tuple[float, float, str, float]

_DEFAULT_DEMO_SIGNALS: tuple[_MockSignalSpec, ...] = (
    (200_000,  -44.0, "nfm",  12_500.0),
    (-300_000, -58.0, "wfm", 200_000.0),
    (500_000,  -72.0, "tone",    500.0),
    (-700_000, -81.0, "tone",  1_000.0),
)


class _MockBackend(SDRBackend):

    def __init__(
        self,
        sample_rate: int = 2_048_000,
        freq_hz: float = 100_000_000.0,
        demo_signals: tuple[_MockSignalSpec, ...] = _DEFAULT_DEMO_SIGNALS,
    ) -> None:
        from modules.rf.rf_mock import MockSDRManager, SyntheticSignal

        self._manager = MockSDRManager(sample_rate=sample_rate)
        self._freq_hz = freq_hz
        self._sample_rate = sample_rate
        self._time_offset = 0.0
        self.hw_name = f"MockSDR sr={sample_rate / 1e6:.3f} MHz"

        for freq_offset, power_dbm, mode, bw_hz in demo_signals:
            self._manager.add_signal(
                SyntheticSignal(
                    freq_offset=freq_offset,
                    power_dbm=power_dbm,
                    mode=mode,
                    bw_hz=bw_hz,
                )
            )

        _register_backend(self)
        log.info("Mock backend initialised: %s", self.hw_name)

    def read_raw(self, n_samples: int) -> np.ndarray | None:
        iq = self._manager.capture(
            int(self._freq_hz), n_samples, t_offset=self._time_offset
        )
        self._time_offset += n_samples / self._sample_rate
        return iq

    def tune(self, freq_hz: float) -> None:
        self._freq_hz = freq_hz

    def set_gain(self, gain: GainValue) -> None:
        pass

    def close(self) -> None:
        pass


def open_rtlsdr_backend(
    freq_hz: float = 100_000_000.0,
    sample_rate: int = 2_048_000,
    gain: float = 49.6,
    ppm: int = 0,
    device_index: int = 0,
) -> SDRBackend:
    try:
        return _RTLSDRBackend(freq_hz, sample_rate, gain, ppm, device_index)
    except ImportError:
        raise
    except Exception as exc:
        log.warning(
            "RTL-SDR unavailable (%s); falling back to MockBackend", exc
        )
        return _MockBackend(sample_rate, freq_hz)


def open_tcp_backend(
    host: str = "127.0.0.1",
    port: int = 1234,
    freq_hz: float = 100_000_000.0,
    sample_rate: int = 2_048_000,
    gain: int = 400,
) -> SDRBackend:
    return _TCPBackend(host, port, freq_hz, sample_rate, gain)


def open_file_backend(path: str, loop: bool = True) -> SDRBackend:
    return _FileBackend(path, loop)


def open_mock_backend(
    sample_rate: int = 2_048_000,
    freq_hz: float = 100_000_000.0,
    demo_signals: tuple[_MockSignalSpec, ...] = _DEFAULT_DEMO_SIGNALS,
) -> SDRBackend:
    return _MockBackend(sample_rate, freq_hz, demo_signals)


open_backend = open_rtlsdr_backend
tcp_backend  = open_tcp_backend
file_backend = open_file_backend
mock_backend = open_mock_backend
