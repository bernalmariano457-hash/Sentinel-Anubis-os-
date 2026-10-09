from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class PowerManager:

    TEMP_WARNING = 75.0
    TEMP_CRITICAL = 82.0
    TEMP_HISTERESIS = 5.0

    def __init__(self, sentinel: Any) -> None:

        self._sentinel = sentinel
        self._log = getattr(sentinel, "log", None)
        self._console = getattr(sentinel, "console", None)

        self._temp = 0.0
        self._throttled = False
        self._stop_event = threading.Event()
        self._thermal_thread: threading.Thread | None = None
        self._throttled_callbacks: list[Callable[[bool], None]] = []
        self._is_rpi = self._detect_rasperry()

        self._info(
            f"Inicializado | RPi={self._is_rpi} | uConsole={self._is_uconcole}")

        def _detect_raspberry(self) -> bool:
        try:
            with open("/proc/cpuinfo") as f:
                content = f.read()
            return "Raspberry" in content or "BCM" in content
        except OSError:
            return False

    def _detect_uconsole(self) -> bool:
        try:
            with open("/proc/device-tree/model") as f:
                model = f.read()
            return "uConsole" in model or "Clockwork" in model
        except OSError:
            return False

    def _info(self, msg: str) -> None:
        if self._log:
            self._log.info(msg, "PowerManager")

    def _warn(self, msg: str) -> None:
        if self._log:
            self._log.warning(msg, "PowerManager")

    def _err(self, msg: str) -> None:
        if self._log:
            self._log.error(msg, "PowerManager")

    @staticmethod
    def _run(cmd: list[str], timeout: float = 5.0) -> tuple[str, int]:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, check=False,
            )
            return r.stdout.strip(), r.returncode
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return "", -1

    def get_temperature(self) -> float:
        if not self._is_rpi:
            return 0.0
        out, rc = self._run(["vcgencmd", "measure_temp"])
        if rc == 0 and out.startswith("temp="):
            try:
                return float(out.replace("temp=", "").replace("'C", ""))
            except ValueError:
                return 0.0
        return 0.0

    def get_throttled_status(self) -> int:
        out, rc = self._run(["vcgencmd", "get_throttled"])
        if rc == 0 and out.startswith("throttled="):
            try:
                return int(out.replace("throttled=", ""), 16)
            except ValueError:
                return 0
        return 0

    def get_battery_level(self) -> int | None:
        try:
            for bat in Path("/sys/class/power_supply").glob("BAT*"):
                cap = bat / "capacity"
                if cap.exists():
                    return int(cap.read_text().strip())
        except (OSError, ValueError):
            pass
        return None

    def is_charging(self) -> bool:
        try:
            for bat in Path("/sys/class/power_supply").glob("BAT*"):
                status = bat / "status"
                if status.exists():
                    return "Charging" in status.read_text()
        except OSError:
            pass
        return False

    def is_sdr_available(self) -> bool:
        out, rc = self._run(["lsusb"])
        if rc != 0:
            return False
        return "0bda:2838" in out or "Realtek" in out

    def toggle_sdr(self, state: bool) -> bool:
        if not (self._is_uconsole or self._is_rpi):
            return False
        action = "on" if state else "off"
        _, rc = self._run(
            ["sudo", "uhubctl", "-l", "1-1", "-p", "2", "-a", action])
        if rc == 0:
            self._info(f"SDR {'ON' if state else 'OFF'}")
            return True
        self._warn("uhubctl falló (¿instalado?)")
        return False

    def toggle_wifi(self, state: bool) -> bool:
        _, rc = self._run(["nmcli", "radio", "wifi", "on" if state else "off"])
        return rc == 0

    def toggle_bluetooth(self, state: bool) -> bool:
        _, rc = self._run(
            ["rfkill", "unblock" if state else "block", "bluetooth"])
        return rc == 0

    def start_thermal_monitor(self, interval: float = 5.0) -> None:
        if self._thermal_thread and self._thermal_thread.is_alive():
            return
        if not self._is_rpi:
            self._info("Monitor térmico omitido (plataforma no soportada)")
            return
        self._stop_event.clear()
        self._thermal_thread = threading.Thread(
            target=self._thermal_loop, args=(interval,),
            name="PowerManager-Thermal", daemon=True,
        )
        self._thermal_thread.start()
        self._info("Monitor térmico iniciado")

    def _thermal_loop(self, interval: float) -> None:
        while not self._stop_event.is_set():
            temp = self.get_temperature()
            self._temp = temp

            if temp >= self.TEMP_CRITICAL and not self._throttled:
                self._warn(
                    f"Temperatura crítica: {temp:.1f}°C → throttling ON")
                self._apply_throttle(True)
                self._throttled = True
            elif temp < (self.TEMP_WARNING - self.TEMP_HISTERESIS) and self._throttled:
                self._info(
                    f"Temperatura estable: {temp:.1f}°C → throttling OFF")
                self._apply_throttle(False)
                self._throttled = False

            self._stop_event.wait(interval)

    def _apply_throttle(self, enable: bool) -> None:
        gov = "powersave" if enable else "ondemand"
        self._run(["sudo", "cpufreq-set", "-g", gov])
        for cb in self._throttle_callbacks:
            try:
                cb(enable)
            except Exception as exc:
                self._err(f"Callback throttle falló: {exc}")

    def register_throttle_callback(self, cb: Callable[[bool], None]) -> None:
        self._throttle_callbacks.append(cb)

    def status(self) -> None:
        if not self._console:
            return
        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold steel_blue1")
        tabla.add_column("Parámetro", style="cyan")
        tabla.add_column("Valor", style="white")

        temp = self._temp or self.get_temperature()
        tabla.add_row("Temperatura", f"{temp:.1f} °C")
        tabla.add_row("Throttled", "Sí" if self._throttled else "No")
        tabla.add_row("Estado HW", f"0x{self.get_throttled_status():X}")

        bat = self.get_battery_level()
        tabla.add_row("Batería", f"{bat}%" if bat is not None else "N/D")
        tabla.add_row("Cargando", "Sí" if self.is_charging() else "No")

        tabla.add_row("SDR detectado",
                      "Sí" if self.is_sdr_available() else "No")
        tabla.add_row("Plataforma", self._platform_name())

        self._console.print(Panel(
            tabla, title="[bold]POWER MANAGER[/bold]",
            border_style="steel_blue1", box=box.ROUNDED,
        ))

    def mostrar_temperatura(self) -> None:
        if not self._console:
            return
        temp = self.get_temperature()
        color = "green" if temp < self.TEMP_WARNING else (
            "yellow" if temp < self.TEMP_CRITICAL else "red")
        self._console.print(
            f"[steel_blue1]Temperatura:[/steel_blue1] "
            f"[{color}]{temp:.1f} °C[/{color}]"
        )

    def mostrar_bateria(self) -> None:
        if not self._console:
            return
        bat = self.get_battery_level()
        if bat is None:
            self._console.print("[orange3]Batería: no detectada[/orange3]")
            return
        color = "green" if bat > 30 else ("yellow" if bat > 15 else "red")
        carga = " (cargando)" if self.is_charging() else ""
        self._console.print(
            f"[steel_blue1]Batería:[/steel_blue1] "
            f"[{color}]{bat}%[/{color}]{carga}"
        )

    def toggle_throttle(self, args: list[str]) -> None:
        if not args:
            self._console.print(
                "[orange3]Uso: throttle [on|off|auto][/orange3]")
            return
        accion = args[0].lower()
        if accion == "on":
            self._apply_throttle(True)
            self._throttled = True
            self._console.print("[yellow]Throttling forzado ON[/yellow]")
        elif accion == "off":
            self._apply_throttle(False)
            self._throttled = False
            self._console.print("[green]Throttling forzado OFF[/green]")
        elif accion == "auto":
            self._throttled = False
            self._console.print(
                "[cyan]Throttling automático restaurado[/cyan]")
        else:
            self._console.print(f"[red]Acción desconocida: {accion}[/red]")

    def _platform_name(self) -> str:
        if self._is_uconsole:
            return "uConsole CM4"
        if self._is_rpi:
            return "Raspberry Pi"
        return "Genérica / Desarrollo"

    def cleanup(self) -> None:
        self._stop_event.set()
        if self._thermal_thread and self._thermal_thread.is_alive():
            self._thermal_thread.join(timeout=2.0)
        if self._throttled:
            self._apply_throttle(False)
        self._info("PowerManager detenido")
