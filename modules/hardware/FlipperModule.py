from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from Main import ApexSentinel


try:
    from flipper_bridge import (
        FlipperBridge,
        FlipperError,
        FlipperConnectionError,
        FlipperTimeoutError,
        FlipperCommandError,
    )
    _BRIDGE_OK = True
except ImportError:
    _BRIDGE_OK = False


class FlipperModule:

    NOMBRE_MODULO = "FlipperZero"

    def __init__(self, sentinel: "ApexSentinel") -> None:
        self._sentinel = sentinel
        self._console = sentinel.console
        self._log = sentinel.log
        self._bridge: Optional["FlipperBridge"] = None
        self.disponible: bool = _BRIDGE_OK

        if not _BRIDGE_OK:
            self._log.warning(
                "flipper_bridge.py no encontrado — módulo deshabilitado.",
                self.NOMBRE_MODULO,
            )

    def _conectar(self) -> bool:
        if not self.disponible:
            self._console.print(
                "[orange3][!] flipper_bridge no disponible. "
                "Coloca flipper_bridge.py en el directorio raíz.[/orange3]"
            )
            return False

        try:
            self._bridge = FlipperBridge()
            self._bridge.connect()
            self._log.info("Flipper Zero conectado.", self.NOMBRE_MODULO)
            return True
        except FlipperConnectionError as exc:
            self._console.print(
                f"[red][!] No se pudo conectar al Flipper Zero: {exc}[/red]")
            self._log.error(str(exc), self.NOMBRE_MODULO)
            self._bridge = None
            return False
        except Exception as exc:
            self._console.print(
                f"[red][!] Error inesperado al conectar: {exc}[/red]")
            self._log.error(str(exc), self.NOMBRE_MODULO)
            self._bridge = None
            return False

    def _desconectar(self) -> None:
        if self._bridge and self._bridge.is_connected:
            try:
                self._bridge.disconnect()
            except Exception:
                pass
        self._bridge = None

    def _ok(self, mensaje: str) -> None:
        self._console.print(f"[sea_green3][✔][/sea_green3] {mensaje}")

    def _warn(self, mensaje: str) -> None:
        self._console.print(f"[orange3][!][/orange3] {mensaje}")

    def _err(self, mensaje: str) -> None:
        self._console.print(f"[red][✖][/red] {mensaje}")

    def _campo(self, etiqueta: str, valor: str) -> None:
        self._console.print(
            f"  [grey58]{etiqueta:<18}[/grey58][white]{valor}[/white]"
        )

    def _separador(self) -> None:
        self._console.print("[grey42]─" * 42 + "[/grey42]")

    def status(self) -> None:
        self._console.print(
            "\n[bold steel_blue1]  Flipper Zero — Telemetría[/bold steel_blue1]")
        self._separador()

        if not self._conectar():
            return

        try:
            reporte = self._bridge.telemetry.full_report()

            bat = reporte.get("battery", {})
            self._campo("Batería",     bat.get("charge_percent") or "—")
            self._campo("Voltaje",     bat.get("voltage") or "—")
            self._campo("Corriente",   bat.get("current") or "—")
            self._campo("Salud bat.",  bat.get("health") or "—")

            temp = reporte.get("temperature_c")
            self._campo("Temperatura", f"{temp} °C" if temp else "—")

            sto = reporte.get("storage", {})
            if sto:
                self._campo("Almac. total",  sto.get("total") or "—")
                self._campo("Almac. libre",  sto.get("free") or "—")

            self._log.info("Telemetría Flipper obtenida.", self.NOMBRE_MODULO)

        except FlipperError as exc:
            self._err(f"Error de comunicación: {exc}")
            self._log.error(str(exc), self.NOMBRE_MODULO)
        finally:
            self._desconectar()

        self._separador()
        self._console.print()

    def nfc_scan(self) -> None:
        self._console.print(
            "\n[bold steel_blue1]  Flipper Zero — Escaneo NFC[/bold steel_blue1]")
        self._separador()

        timeout = 7
        try:
            raw = self._console.input(
                "[grey58]  Timeout en segundos (Enter = 7): [/grey58]"
            ).strip()
            if raw.isdigit():
                timeout = int(raw)
        except (KeyboardInterrupt, EOFError):
            self._console.print()

        self._console.print(
            "[grey58]  Acerca la tarjeta al lector NFC del Flipper...[/grey58]")

        if not self._conectar():
            return

        try:
            resultado = self._bridge.nfc.scan(timeout_s=timeout)
            if resultado.get("found"):
                self._ok("Tarjeta detectada")
                self._campo("UID",  resultado.get("uid") or "—")
                self._campo("Tipo", resultado.get("type") or "—")
                self._log.info(
                    f"NFC detectado: uid={resultado.get('uid')} tipo={resultado.get('type')}",
                    self.NOMBRE_MODULO,
                )
            else:
                self._warn(
                    "No se detectó ninguna tarjeta NFC en el tiempo indicado.")
        except FlipperTimeoutError:
            self._warn("Tiempo de espera agotado. Ninguna tarjeta detectada.")
        except FlipperError as exc:
            self._err(f"Error NFC: {exc}")
            self._log.error(str(exc), self.NOMBRE_MODULO)
        finally:
            self._desconectar()

        self._separador()
        self._console.print()

    def rfid_scan(self) -> None:
        self._console.print(
            "\n[bold steel_blue1]  Flipper Zero — Lectura RFID 125 kHz[/bold steel_blue1]")
        self._separador()

        timeout = 7
        try:
            raw = self._console.input(
                "[grey58]  Timeout en segundos (Enter = 7): [/grey58]"
            ).strip()
            if raw.isdigit():
                timeout = int(raw)
        except (KeyboardInterrupt, EOFError):
            self._console.print()

        self._console.print(
            "[grey58]  Acerca la tarjeta RFID al Flipper...[/grey58]")

        if not self._conectar():
            return

        try:
            resultado = self._bridge.nfc.read_lf_uid(timeout_s=timeout)
            if resultado.get("found"):
                self._ok("Tarjeta LF detectada")
                self._campo("UID",  resultado.get("uid") or "—")
                self._campo("Tipo", resultado.get("type") or "—")
                self._log.info(
                    f"RFID-LF detectado: uid={resultado.get('uid')}",
                    self.NOMBRE_MODULO,
                )
            else:
                self._warn(
                    "No se detectó ninguna tarjeta LF en el tiempo indicado.")
        except FlipperTimeoutError:
            self._warn("Tiempo de espera agotado.")
        except FlipperError as exc:
            self._err(f"Error RFID: {exc}")
            self._log.error(str(exc), self.NOMBRE_MODULO)
        finally:
            self._desconectar()

        self._separador()
        self._console.print()

    def subghz_capture(self) -> None:
        self._console.print(
            "\n[bold steel_blue1]  Flipper Zero — Captura Sub-GHz[/bold steel_blue1]")
        self._separador()

        try:
            freq_raw = self._console.input(
                "[grey58]  Frecuencia en Hz (ej. 433920000): [/grey58]"
            ).strip()
            if not freq_raw.isdigit():
                self._warn("Frecuencia inválida.")
                return
            frecuencia = int(freq_raw)

            dur_raw = self._console.input(
                "[grey58]  Duración en segundos (ej. 5): [/grey58]"
            ).strip()
            if not dur_raw.isdigit():
                self._warn("Duración inválida.")
                return
            duracion = int(dur_raw)

            nombre = self._console.input(
                "[grey58]  Nombre del archivo (sin .sub): [/grey58]"
            ).strip()
            if not nombre:
                self._warn("Nombre de archivo vacío.")
                return

        except (KeyboardInterrupt, EOFError):
            self._console.print("\n[grey58]  Cancelado.[/grey58]")
            return

        self._console.print(
            f"[grey58]  Capturando {frecuencia/1e6:.3f} MHz durante {duracion}s...[/grey58]"
        )

        if not self._conectar():
            return

        try:
            ruta = self._bridge.subghz.capture(frecuencia, duracion, nombre)
            self._ok(f"Captura guardada en el Flipper: {ruta}")
            self._log.info(
                f"Sub-GHz capturado: {ruta} @ {frecuencia} Hz {duracion}s",
                self.NOMBRE_MODULO,
            )
        except FlipperError as exc:
            self._err(f"Error en captura Sub-GHz: {exc}")
            self._log.error(str(exc), self.NOMBRE_MODULO)
        finally:
            self._desconectar()

        self._separador()
        self._console.print()

    def subghz_list(self) -> None:
        self._console.print(
            "\n[bold steel_blue1]  Flipper Zero — Archivos Sub-GHz[/bold steel_blue1]")
        self._separador()

        if not self._conectar():
            return

        try:
            capturas = self._bridge.subghz.list_captures()
            if capturas:
                for idx, nombre in enumerate(capturas, 1):
                    self._console.print(
                        f"  [grey58]{idx:>3}.[/grey58] [white]{nombre}[/white]"
                    )
                self._console.print(
                    f"\n  [grey58]Total: {len(capturas)} archivo(s)[/grey58]"
                )
            else:
                self._warn("No hay archivos .sub en /ext/subghz/")
        except FlipperError as exc:
            self._err(f"Error listando capturas: {exc}")
            self._log.error(str(exc), self.NOMBRE_MODULO)
        finally:
            self._desconectar()

        self._separador()
        self._console.print()

    def menu(self) -> None:
        opciones = {
            "1": ("Telemetría del dispositivo",  self.status),
            "2": ("Escaneo NFC (HF)",             self.nfc_scan),
            "3": ("Lectura RFID (LF 125 kHz)",    self.rfid_scan),
            "4": ("Captura Sub-GHz",              self.subghz_capture),
            "5": ("Listar capturas Sub-GHz",      self.subghz_list),
            "0": ("Volver",                        None),
        }

        while True:
            self._console.print(
                "\n[bold steel_blue1]  ◈ Flipper Zero — Menú[/bold steel_blue1]")
            self._separador()
            for key, (desc, _) in opciones.items():
                marca = "[grey58]→[/grey58]" if key != "0" else "[grey42]←[/grey42]"
                self._console.print(
                    f"  {marca} [bold steel_blue1]{key}[/bold steel_blue1]  {desc}")
            self._separador()

            try:
                seleccion = self._console.input(
                    "[grey58]  Selección: [/grey58]"
                ).strip()
            except (KeyboardInterrupt, EOFError):
                break

            if seleccion == "0":
                break

            entrada = opciones.get(seleccion)
            if entrada is None:
                self._warn("Opción no válida.")
                continue

            _, accion = entrada
            if accion:
                accion()
