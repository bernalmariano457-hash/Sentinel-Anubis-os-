from __future__ import annotations

import atexit
import socket
import struct
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

Source = Callable[[], Optional[bytes]]
SourceFactory = Callable[[float, int], "Source"]

_IQ_SCALE = 1.0 / 127.5


def _u8_to_cf32(raw: bytes) -> np.ndarray:
    arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    arr = arr * _IQ_SCALE - 1.0
    return arr[0::2] + 1j * arr[1::2]


def _cf32_to_u8(iq: np.ndarray) -> bytes:
    i = (np.real(iq) * 127.5 + 127.5).clip(0, 255).astype(np.uint8)
    q = (np.imag(iq) * 127.5 + 127.5).clip(0, 255).astype(np.uint8)
    out = np.empty(len(i) * 2, dtype=np.uint8)
    out[0::2] = i
    out[1::2] = q
    return out.tobytes()


def rtlsdr_source(
    freq_hz:      float,
    sample_rate:  int = 2_048_000,
    gain:         float = 49.6,
    ppm:          int = 0,
    device_index: int = 0,
) -> Source:
    try:
        from rtlsdr import RtlSdr
    except ImportError:
        raise ImportError(
            "pyrtlsdr no instalado:\n"
            "  pip install pyrtlsdr --break-system-packages"
        )

    sdr = RtlSdr(device_index=device_index)
    sdr.sample_rate = sample_rate
    sdr.center_freq = int(freq_hz)
    sdr.gain = gain
    sdr.freq_correction = ppm
    chunk = sample_rate // 10

    def _close() -> None:
        try:
            sdr.close()
        except Exception:
            pass

    atexit.register(_close)

    def _read() -> bytes:
        samples = sdr.read_samples(chunk)
        return _cf32_to_u8(samples)

    return _read


def tcp_source(
    host:        str = "127.0.0.1",
    port:        int = 1234,
    freq_hz:     float = 100_000_000.0,
    sample_rate: int = 2_048_000,
    gain:        int = 400,
    chunk_bytes: int = 131_072,
) -> Source:
    # rtl_tcp wire protocol — big-endian command: 1-byte cmd + 4-byte param
    def _cmd(sock: socket.socket, cmd: int, param: int) -> None:
        sock.sendall(struct.pack(">BI", cmd, param))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.connect((host, port))
    sock.settimeout(5.0)

    # Read 12-byte magic header from rtl_tcp
    sock.recv(12)

    _cmd(sock, 0x01, int(freq_hz))     # set frequency
    _cmd(sock, 0x02, sample_rate)      # set sample rate
    _cmd(sock, 0x04, gain)             # set gain (tenths of dB)
    _cmd(sock, 0x03, 1)                # manual gain mode

    def _close() -> None:
        try:
            sock.close()
        except Exception:
            pass

    atexit.register(_close)

    def _read() -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < chunk_bytes:
            try:
                chunk = sock.recv(chunk_bytes - len(buf))
                if not chunk:
                    return None
                buf.extend(chunk)
            except socket.timeout:
                return bytes(buf) if buf else None
        return bytes(buf)

    return _read


def file_source(
    path:        str,
    chunk_bytes: int = 131_072,
    loop:        bool = True,
) -> Source:
    fh = open(path, "rb")
    atexit.register(fh.close)

    def _read() -> Optional[bytes]:
        data = fh.read(chunk_bytes)
        if not data:
            if loop:
                fh.seek(0)
                data = fh.read(chunk_bytes)
            else:
                return None
        return data or None

    return _read


def null_source() -> Source:
    return lambda: None


# ═══════════════════════════════════════════════════════════════════════════
# TUNABLE BACKEND — backend resintonizable compartido por RFScanner
#                   y SpectrumAnalyzer. Reemplaza todos los _SDRAdapter
#                   locales y entrega TCP + replay de archivo IQ gratis.
# ═══════════════════════════════════════════════════════════════════════════

class SDRBackend:
    hw_name: str = "Unknown"

    def read_raw(self, n_samples: int) -> Optional[np.ndarray]:
        """Lee n_samples muestras IQ como np.ndarray complex64."""
        raise NotImplementedError

    def tune(self, freq_hz: float) -> None:
        """Resintoniza a la frecuencia indicada (Hz).  No-op en modo archivo."""

    def set_gain(self, gain: object) -> None:
        """Ajusta la ganancia.  Acepta float, int o la cadena 'auto'."""

    def close(self) -> None:
        """Libera el recurso subyacente."""

    # ------------------------------------------------------------------
    # Compatibilidad con la interfaz SourceFactory de NOAADecoder
    # ------------------------------------------------------------------
    def as_source(self, sample_rate: int) -> "Source":
        """
        Envuelve este backend como un Source callable (bytes u8 IQ)
        compatible con NOAADecoder / cualquier consumidor de SourceFactory.
        """
        chunk = sample_rate // 10

        def _read() -> Optional[bytes]:
            iq = self.read_raw(chunk)
            return None if iq is None else _cf32_to_u8(iq)

        return _read


# ── RTL-SDR (pyrtlsdr) ────────────────────────────────────────────────────

class _RTLSDRBackend(SDRBackend):
    def __init__(
        self,
        freq_hz:      float,
        sample_rate:  int,
        gain:         float,
        ppm:          int,
        device_index: int,
    ) -> None:
        from rtlsdr import RtlSdr  # fallo explícito si no está instalado

        sdr = RtlSdr(device_index=device_index)
        sdr.sample_rate = sample_rate
        sdr.center_freq = int(freq_hz)
        sdr.gain = gain
        sdr.freq_correction = ppm
        self._sdr = sdr
        self._sr = sample_rate
        self.hw_name = (
            f"RTL-SDR idx={device_index} "
            f"sr={sample_rate / 1e6:.3f} MHz  gain={gain} dB"
        )
        atexit.register(self.close)

    def read_raw(self, n_samples: int) -> Optional[np.ndarray]:
        try:
            return np.array(
                self._sdr.read_samples(n_samples), dtype=np.complex64
            )
        except Exception:
            return None

    def tune(self, freq_hz: float) -> None:
        self._sdr.center_freq = int(freq_hz)

    def set_gain(self, gain: object) -> None:
        self._sdr.gain = gain  # acepta float o "auto"

    def close(self) -> None:
        try:
            self._sdr.close()
        except Exception:
            pass


# ── rtl_tcp ───────────────────────────────────────────────────────────────

class _TCPBackend(SDRBackend):
    def __init__(
        self,
        host:        str,
        port:        int,
        freq_hz:     float,
        sample_rate: int,
        gain:        int,
    ) -> None:
        self._host = host
        self._port = port
        self._sr = sample_rate
        self._gain = gain
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()
        self.hw_name = f"rtl_tcp://{host}:{port}  sr={sample_rate / 1e6:.3f} MHz"
        self._connect(freq_hz)
        atexit.register(self.close)

    # protocolo rtl_tcp: comando 1 byte + parámetro 4 bytes big-endian
    @staticmethod
    def _cmd(sock: socket.socket, cmd: int, param: int) -> None:
        sock.sendall(struct.pack(">BI", cmd, param))

    def _connect(self, freq_hz: float) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.connect((self._host, self._port))
        sock.settimeout(5.0)
        sock.recv(12)                                 # cabecera mágica rtl_tcp
        self._cmd(sock, 0x01, int(freq_hz))           # set frequency
        self._cmd(sock, 0x02, self._sr)               # set sample rate
        self._cmd(sock, 0x04, self._gain)             # set gain (décimas dB)
        self._cmd(sock, 0x03, 1)                      # manual gain mode
        self._sock = sock
        self._freq_hz = freq_hz

    def read_raw(self, n_samples: int) -> Optional[np.ndarray]:
        if self._sock is None:
            return None
        needed = n_samples * 2
        while len(self._buf) < needed:
            try:
                chunk = self._sock.recv(65_536)
                if not chunk:
                    return None
                self._buf.extend(chunk)
            except socket.timeout:
                break
        if len(self._buf) < needed:
            return None
        raw = bytes(self._buf[:needed])
        del self._buf[:needed]
        return _u8_to_cf32(raw)

    def tune(self, freq_hz: float) -> None:
        if self._sock:
            try:
                self._cmd(self._sock, 0x01, int(freq_hz))
                self._freq_hz = freq_hz
            except Exception:
                try:
                    self.close()
                    self._connect(freq_hz)
                except Exception:
                    pass

    def set_gain(self, gain: object) -> None:
        if self._sock:
            try:
                g = 0 if str(gain).lower() == "auto" else int(float(gain) * 10)
                self._cmd(self._sock, 0x04, g)
            except Exception:
                pass

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


# ── Archivo IQ (replay) ───────────────────────────────────────────────────

class _FileBackend(SDRBackend):
    def __init__(self, path: str, loop: bool = True) -> None:
        self._fh = open(path, "rb")
        self._loop = loop
        self.hw_name = f"FILE:{Path(path).name}"
        atexit.register(self.close)

    def read_raw(self, n_samples: int) -> Optional[np.ndarray]:
        needed = n_samples * 2  # pares u8 I+Q
        data = self._fh.read(needed)
        if not data:
            if self._loop:
                self._fh.seek(0)
                data = self._fh.read(needed)
            if not data:
                return None
        if len(data) % 2:
            data = data[:-1]
        return _u8_to_cf32(data)

    def tune(self, freq_hz: float) -> None:
        pass  # los archivos no se resintoizan; no-op intencional

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


# ── Mock (señales sintéticas, sin hardware) ───────────────────────────────

class _MockBackend(SDRBackend):
    def __init__(
        self,
        sample_rate: int = 2_048_000,
        freq_hz:     float = 100_000_000.0,
        add_demo_signals: bool = True,
    ) -> None:
        from modules.rf.rf_mock import MockSDRManager, SyntheticSignal

        self._mock = MockSDRManager(sample_rate=sample_rate)
        self._freq = freq_hz
        self._sr = sample_rate
        self._toff = 0.0
        self.hw_name = f"MockSDR  sr={sample_rate / 1e6:.3f} MHz"

        if add_demo_signals:
            for offset, pwr, mode, bw in (
                (200_000, -44.0, "nfm",   12_500.0),
                (-300_000, -58.0, "wfm",  200_000.0),
                (500_000, -72.0, "tone",     500.0),
                (-700_000, -81.0, "tone",   1_000.0),
            ):
                self._mock.add_signal(
                    SyntheticSignal(
                        freq_offset=offset, power_dbm=pwr,
                        mode=mode, bw_hz=bw,
                    )
                )

    def read_raw(self, n_samples: int) -> Optional[np.ndarray]:
        iq = self._mock.capture(
            int(self._freq), n_samples, t_offset=self._toff)
        self._toff += n_samples / self._sr
        return iq

    def tune(self, freq_hz: float) -> None:
        self._freq = freq_hz

    def set_gain(self, gain: object) -> None:
        pass  # Mock no tiene ganancia física

    def close(self) -> None:
        pass


# ── Funciones de fábrica públicas ─────────────────────────────────────────

def open_backend(
    freq_hz:      float = 100_000_000.0,
    sample_rate:  int = 2_048_000,
    gain:         float = 49.6,
    ppm:          int = 0,
    device_index: int = 0,
) -> SDRBackend:
    try:
        return _RTLSDRBackend(freq_hz, sample_rate, gain, ppm, device_index)
    except Exception:
        pass
    return _MockBackend(sample_rate, freq_hz)


def tcp_backend(
    host:        str = "127.0.0.1",
    port:        int = 1234,
    freq_hz:     float = 100_000_000.0,
    sample_rate: int = 2_048_000,
    gain:        int = 400,
) -> SDRBackend:
    return _TCPBackend(host, port, freq_hz, sample_rate, gain)


def file_backend(path: str, loop: bool = True) -> SDRBackend:
    return _FileBackend(path, loop)


def mock_backend(
    sample_rate: int = 2_048_000,
    freq_hz:     float = 100_000_000.0,
) -> SDRBackend:
    return _MockBackend(sample_rate, freq_hz)
