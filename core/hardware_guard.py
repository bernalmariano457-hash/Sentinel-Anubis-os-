from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class HardwareGuard:

    MIN_DISK_FREE_MB = 100
    MAX_CPU_TEMP = 80
    MIN_BATTERY_PCT = 5

    @staticmethod
    def check_disk_space(path: Path | str = ".") -> bool:
        try:
            _, _, free = shutil.disk_usage(path)
            free_mb = free // (1024 * 1024)
            if free_mb < HardwareGuard.MIN_DISK_FREE_MB:
                logger.error(f"Espacio en disco crítico: {free_mb} MB libres.")
                return False
            return True
        except Exception as e:
            logger.warning(f"No se pudo verificar el disco: {e}")
            return True

    @staticmethod
    def check_thermal_and_power(power_module: object) -> tuple[bool, str]:
        if power_module is None:
            return True, "PowerManager no disponible"

        try:
            temp = getattr(power_module, "get_temperature", lambda: 40)()
            bat = getattr(power_module, "get_battery", lambda: 100)()

            if temp >= HardwareGuard.MAX_CPU_TEMP:
                return False, f"Temperatura crítica: {temp}°C. Espera a que enfríe."

            if bat <= HardwareGuard.MIN_BATTERY_PCT:
                return False, f"Batería crítica: {bat}%. Conecta el cargador."

            return True, "OK"
        except Exception as e:
            logger.warning(f"Fallo leyendo telemetría: {e}")
            return True, "OK"
