from __future__ import annotations

import atexit
import socket
import struct
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

Source        = Callable[[], Optional[bytes]]
SourceFactory = Callable[[float, int], "Source"]

_IQ_SCALE = 1.0 / 127.5


def _u8_to_cf32(raw: bytes) -> np.ndarray:
    arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    arr = arr * _IQ_SCALE - 1.0
    return arr[0::2] + 1j * arr[1::2]


def _cf32_to_u8(iq: np.ndarray) -> bytes:
    i = (np.real(iq) * 127.5 + 127.5).clip(0, 255).astype(np.uint8)
    q = (np.imag(iq) * 127.5 + 127.5).clip(0, 255).astype(np.uint8)
    out        = np.empty(len(i) * 2, dtype=np.uint8)
    out[0::2]  = i
    out[1::2]  = q
    return out.tobytes()


def rtlsdr_source(
    freq_hz:      float,
    sample_rate:  int   = 2_048_000,
    gain:         float = 49.6,
    ppm:          int   = 0,
    device_index: int   = 0,
) -> Source:
    try:
        from rtlsdr import RtlSdr
    except ImportError:
        raise ImportError(
            "pyrtlsdr no instalado:\n"
            "  pip install pyrtlsdr --break-system-packages"
        )

    sdr               = RtlSdr(device_index=device_index)
    sdr.sample_rate   = sample_rate
    sdr.center_freq   = int(freq_hz)
    sdr.gain          = gain
    sdr.freq_correction = ppm
    chunk             = sample_rate // 10

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
    host:        str   = "127.0.0.1",
    port:        int   = 1234,
    freq_hz:     float = 100_000_000.0,
    sample_rate: int   = 2_048_000,
    gain:        int   = 400,
    chunk_bytes: int   = 131_072,
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
    chunk_bytes: int  = 131_072,
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
