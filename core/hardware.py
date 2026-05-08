from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from modules.rf.RFScanner import (
    HardwareConfigError,
    HardwareDisconnectedError,
    HardwareNotFoundError,
)

log = logging.getLogger("rfscanner.hardware")

# ── Detección de librerías disponibles ───────────────────────────
_RTL_OK = False
_SOAPY_OK = False

try:
    from rtlsdr import RtlSdr
    _RTL_OK = True
except ImportError:
    pass

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
    _SOAPY_OK = True
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════════
# VALIDACIÓN DE PERMISOS
# ══════════════════════════════════════════════════════════════════

def check_usb_permissions() -> tuple[bool, str]:
    """
    Verifica que el usuario tiene permisos para acceder al USB.
    Devuelve (ok, mensaje_error).
    """
    # Verificar acceso al bus USB
    usb_path = Path("/dev/bus/usb")
    if not usb_path.exists():
        return False, "/dev/bus/usb no existe — ¿estás en Linux?"

    if not os.access(str(usb_path), os.R_OK):
        user = os.environ.get("USER", "tu_usuario")
        return False, (
            f"Sin permisos para /dev/bus/usb\n"
            f"Ejecuta: sudo usermod -aG plugdev {user}\n"
            f"Luego cierra sesión y vuelve a entrar, o ejecuta: newgrp plugdev\n"
            f"También: sudo udevadm control --reload-rules && sudo udevadm trigger"
        )

    # Verificar que el usuario está en el grupo plugdev
    try:
        import grp
        plugdev = grp.getgrnam("plugdev")
        import pwd
        user_info = pwd.getpwuid(os.getuid())
        user_groups = os.getgroups()
        if plugdev.gr_gid not in user_groups:
            return False, (
                f"Usuario '{user_info.pw_name}' no está en el grupo 'plugdev'\n"
                f"Ejecuta: sudo usermod -aG plugdev {user_info.pw_name}\n"
                f"Luego cierra sesión y vuelve a entrar."
            )
    except (KeyError, ImportError):
        pass  # plugdev no existe en este sistema (macOS, etc.)

    return True, ""


def check_rtlsdr_rules() -> tuple[bool, str]:
    """Verifica que las reglas udev del RTL-SDR están instaladas."""
    rules_paths = [
        Path("/etc/udev/rules.d/rtl-sdr.rules"),
        Path("/lib/udev/rules.d/rtl-sdr.rules"),
        Path("/usr/lib/udev/rules.d/rtl-sdr.rules"),
    ]
    for p in rules_paths:
        if p.exists():
            return True, ""

    return False, (
        "Reglas udev para RTL-SDR no instaladas.\n"
        "Ejecuta: sudo apt install rtl-sdr\n"
        "O copia manualmente: sudo cp /etc/udev/rules.d/rtl-sdr.rules /etc/udev/rules.d/\n"
        "Luego: sudo udevadm control --reload-rules && sudo udevadm trigger"
    )


# ══════════════════════════════════════════════════════════════════
# GESTOR DE HARDWARE
# ══════════════════════════════════════════════════════════════════

class SDRManager:
    """
    Interfaz unificada para RTL-SDR y dispositivos SoapySDR.
    Thread-safe. Soporta reconexión automática.
    """

    def __init__(self, hw_cfg):
        self._cfg = hw_cfg
        self._sdr = None
        self._hw_tipo:    Optional[str] = None
        self._hw_info:    dict = {}
        self._lock = threading.Lock()
        self._sample_rate: float = float(hw_cfg.__class__.__dict__.get(
            'sample_rate', 2_048_000
        ))
        self._connected = False

    # ── Conexión ─────────────────────────────────────────────────

    def connect(self) -> None:
        """
        Detecta y conecta el primer dispositivo SDR disponible.
        Valida permisos antes de intentar abrir el dispositivo.
        Lanza HardwareNotFoundError si no hay dispositivo compatible.
        """
        self._validar_permisos()

        # Cargar sample_rate desde config global
        try:
            from modules.rf.rf_config import cfg as global_cfg
            self._sample_rate = float(global_cfg.dsp.sample_rate)
        except Exception:
            self._sample_rate = 2_048_000.0

        if _RTL_OK and self._try_rtlsdr():
            return
        if _SOAPY_OK and self._try_soapy():
            return

        raise HardwareNotFoundError(
            "No se detectó hardware SDR compatible.\n"
            "Dispositivos soportados: RTL-SDR, HackRF (vía SoapySDR)\n"
            "Diagnóstico:\n"
            f"  RTL-SDR lib: {'✓ instalada' if _RTL_OK else '✗ falta — pip install pyrtlsdr'}\n"
            f"  SoapySDR lib: {'✓ instalada' if _SOAPY_OK else '✗ falta — pip install SoapySDR'}\n"
            "Conecta el dispositivo al USB y ejecuta: rtl_test -t"
        )

    def _validar_permisos(self) -> None:
        """Comprueba permisos USB; lanza HardwareConfigError si fallan."""
        # Solo en Linux
        if not Path("/dev/bus/usb").exists():
            return

        ok, msg = check_usb_permissions()
        if not ok:
            raise HardwareConfigError(f"Permisos insuficientes:\n{msg}")

    def _try_rtlsdr(self) -> bool:
        """Intenta abrir el primer RTL-SDR disponible."""
        try:
            sdr = RtlSdr(self._cfg.device_index)
            sdr.sample_rate = self._sample_rate
            sdr.freq_correction = self._cfg.ppm_correction

            if self._cfg.gain == "auto":
                sdr.gain = "auto"
            else:
                sdr.gain = float(self._cfg.gain)

            # Bias-T (RTL-SDR Blog v3/v4)
            if self._cfg.bias_tee and hasattr(sdr, 'set_bias_tee'):
                sdr.set_bias_tee(True)
                log.info("Bias-T activado")

            self._sdr = sdr
            self._hw_tipo = "RTL-SDR"
            self._hw_info = self._get_rtlsdr_info(sdr)
            self._connected = True
            log.info(f"RTL-SDR conectado — {self._hw_info.get('serial', 'desconocido')} "
                     f"| PPM: {self._cfg.ppm_correction} "
                     f"| Gain: {self._cfg.gain} dB")
            return True

        except Exception as e:
            log.debug(f"RTL-SDR no disponible: {e}")
            return False

    def _try_soapy(self) -> bool:
        """Intenta abrir el primer dispositivo SoapySDR disponible."""
        try:
            resultados = SoapySDR.Device.enumerate()
            if not resultados:
                return False

            dev_args = resultados[0]
            sdr = SoapySDR.Device(dev_args)
            sdr.setSampleRate(SOAPY_SDR_RX, 0, self._sample_rate)

            if self._cfg.gain == "auto":
                sdr.setGainMode(SOAPY_SDR_RX, 0, True)
            else:
                sdr.setGainMode(SOAPY_SDR_RX, 0, False)
                sdr.setGain(SOAPY_SDR_RX, 0, float(self._cfg.gain))

            self._sdr = sdr
            self._hw_tipo = dev_args.get("driver", "SoapySDR")
            self._hw_info = dict(dev_args)
            self._connected = True
            log.info(f"{self._hw_tipo} conectado")
            return True

        except Exception as e:
            log.debug(f"SoapySDR no disponible: {e}")
            return False

    def _get_rtlsdr_info(self, sdr) -> dict:
        info = {"tipo": "RTL-SDR"}
        try:
            if hasattr(sdr, 'get_device_serial_addresses'):
                serials = sdr.get_device_serial_addresses()
                info["serial"] = serials[0] if serials else "N/A"
        except Exception:
            info["serial"] = "N/A"
        return info

    def reconnect(self) -> None:
        """
        Cierra y reabre la conexión hardware.
        Llamado automáticamente por CaptureThread al detectar desconexión.
        """
        log.info("Intentando reconexión SDR...")
        self.close()
        time.sleep(self._cfg.reconnect_delay_s)
        self.connect()

    # ── Lectura de muestras ───────────────────────────────────────

    def read_samples(
        self,
        freq_hz:    float,
        n_muestras: int = 524_288,
        settle_ms:  int = 50,
    ) -> np.ndarray:
        """
        Sintoniza la frecuencia y lee muestras IQ.
        Thread-safe. Lanza HardwareDisconnectedError si el hardware falla.
        """
        if not self._connected or self._sdr is None:
            raise HardwareDisconnectedError("Dispositivo SDR no conectado")

        with self._lock:
            try:
                if self._hw_tipo == "RTL-SDR":
                    return self._read_rtlsdr(freq_hz, n_muestras, settle_ms)
                else:
                    return self._read_soapy(freq_hz, n_muestras, settle_ms)

            except Exception as e:
                # Distinguir errores transitorios de desconexión real
                err_str = str(e).lower()
                if any(x in err_str for x in
                       ["libusb", "usb", "device", "disconnect", "pipe", "overflow"]):
                    self._connected = False
                    raise HardwareDisconnectedError(str(e)) from e
                raise

    def _read_rtlsdr(self, freq_hz: float, n: int, settle_ms: int) -> np.ndarray:
        self._sdr.center_freq = freq_hz
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)
        return self._sdr.read_samples(n)

    def _read_soapy(self, freq_hz: float, n: int, settle_ms: int) -> np.ndarray:
        self._sdr.setFrequency(SOAPY_SDR_RX, 0, freq_hz)
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)

        stream = self._sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self._sdr.activateStream(stream)
        buff = np.zeros(n, dtype=np.complex64)
        sr = self._sdr.readStream(
            stream, [buff], len(buff), timeoutUs=int(5e6))
        self._sdr.deactivateStream(stream)
        self._sdr.closeStream(stream)

        if sr.ret < 0:
            raise HardwareDisconnectedError(
                f"Error SoapySDR readStream: {sr.ret}")
        return buff[:sr.ret]

    # ── Ajustes en caliente ───────────────────────────────────────

    def set_gain(self, gain_db: float) -> None:
        """Ajusta la ganancia en tiempo real."""
        with self._lock:
            if not self._connected:
                return
            try:
                if self._hw_tipo == "RTL-SDR":
                    self._sdr.gain = gain_db
                elif _SOAPY_OK:
                    self._sdr.setGainMode(SOAPY_SDR_RX, 0, False)
                    self._sdr.setGain(SOAPY_SDR_RX, 0, gain_db)
                log.info(f"Ganancia ajustada: {gain_db} dB")
            except Exception as e:
                log.warning(f"Error ajustando ganancia: {e}")

    def set_ppm(self, ppm: int) -> None:
        """Ajusta la corrección PPM del RTL-SDR."""
        with self._lock:
            if self._hw_tipo == "RTL-SDR" and self._sdr:
                try:
                    self._sdr.freq_correction = ppm
                    log.info(f"Corrección PPM ajustada: {ppm}")
                except Exception as e:
                    log.warning(f"Error ajustando PPM: {e}")

    def set_bias_tee(self, enabled: bool) -> None:
        """Activa/desactiva el Bias-T (RTL-SDR Blog v3/v4)."""
        with self._lock:
            if self._hw_tipo == "RTL-SDR" and self._sdr:
                if hasattr(self._sdr, 'set_bias_tee'):
                    self._sdr.set_bias_tee(enabled)
                    log.info(f"Bias-T: {'ON' if enabled else 'OFF'}")
                else:
                    log.warning("Este RTL-SDR no soporta Bias-T")

    # ── Propiedades ───────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def hw_tipo(self) -> Optional[str]:
        return self._hw_tipo

    @property
    def hw_info(self) -> dict:
        return self._hw_info

    @property
    def sample_rate(self) -> float:
        return self._sample_rate

    def close(self) -> None:
        """Cierra la conexión con el hardware SDR."""
        with self._lock:
            if self._sdr and self._connected:
                try:
                    if self._hw_tipo == "RTL-SDR":
                        self._sdr.close()
                    log.info("SDR desconectado limpiamente")
                except Exception as e:
                    log.debug(f"Error cerrando SDR: {e}")
            self._sdr = None
            self._connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
