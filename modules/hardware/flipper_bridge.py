import time
import json
import glob
import sys
import argparse
import serial
import serial.tools.list_ports


VENDOR_ID = 0x0483
PRODUCT_ID = 0x5740
PROMPT = ">: "


class FlipperError(Exception):
    pass


class FlipperConnectionError(FlipperError):
    pass


class FlipperTimeoutError(FlipperError):
    pass


class FlipperCommandError(FlipperError):
    pass


class FlipperSerialManager:
    def __init__(self, port=None, baudrate=115200, timeout=2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None

    def discover_port(self):
        for p in serial.tools.list_ports.comports():
            if p.vid == VENDOR_ID and p.pid == PRODUCT_ID:
                return p.device
        candidates = sorted(glob.glob("/dev/ttyACM*"))
        if candidates:
            return candidates[0]
        return None

    def connect(self, retries=3, delay=1.0):
        target_port = self.port or self.discover_port()
        if not target_port:
            raise FlipperConnectionError("No se encontró ningún dispositivo Flipper Zero conectado")
        last_error = None
        for attempt in range(retries):
            try:
                self.connection = serial.Serial(
                    port=target_port,
                    baudrate=self.baudrate,
                    timeout=self.timeout
                )
                self.port = target_port
                self._flush_startup()
                return True
            except serial.SerialException as exc:
                last_error = exc
                time.sleep(delay)
        raise FlipperConnectionError(f"No se pudo conectar a {target_port}: {last_error}")

    def _flush_startup(self):
        time.sleep(0.3)
        if self.connection and self.connection.in_waiting:
            self.connection.read(self.connection.in_waiting)
        self.connection.write(b"\r\n")
        time.sleep(0.2)
        if self.connection.in_waiting:
            self.connection.read(self.connection.in_waiting)

    def disconnect(self):
        if self.connection and self.connection.is_open:
            self.connection.close()
        self.connection = None

    def reconnect(self):
        self.disconnect()
        return self.connect()

    @property
    def is_connected(self):
        return bool(self.connection and self.connection.is_open)

    def send_command(self, command, wait=0.4, max_wait=5.0):
        if not self.is_connected:
            raise FlipperConnectionError("No hay una conexión activa con el Flipper Zero")
        try:
            self.connection.reset_input_buffer()
            self.connection.write((command + "\r\n").encode("utf-8"))
        except serial.SerialException as exc:
            self.disconnect()
            raise FlipperConnectionError(f"Se perdió la conexión al enviar el comando: {exc}")

        buffer = ""
        elapsed = 0.0
        while elapsed < max_wait:
            time.sleep(wait)
            elapsed += wait
            try:
                waiting = self.connection.in_waiting
                chunk = self.connection.read(waiting if waiting else 1)
            except serial.SerialException as exc:
                self.disconnect()
                raise FlipperConnectionError(f"Se perdió la conexión durante la lectura: {exc}")
            if chunk:
                buffer += chunk.decode("utf-8", errors="ignore")
                if buffer.rstrip().endswith(PROMPT.strip()):
                    break

        if not buffer:
            raise FlipperTimeoutError(f"Tiempo de espera agotado ejecutando: {command}")

        return self._clean_response(buffer, command)

    def _clean_response(self, raw, command):
        lines = raw.replace("\r", "").split("\n")
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == command.strip():
                continue
            if stripped == PROMPT.strip() or stripped.endswith(PROMPT.strip()):
                continue
            cleaned.append(stripped)
        return "\n".join(cleaned)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


class FlipperTelemetry:
    def __init__(self, manager):
        self.manager = manager

    def _parse_kv_block(self, raw):
        data = {}
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            data[key.strip().lower().replace(" ", "_")] = value.strip()
        return data

    def battery_status(self):
        raw = self.manager.send_command("power info")
        data = self._parse_kv_block(raw)
        return {
            "charge_percent": data.get("charge") or data.get("charge_level"),
            "voltage": data.get("battery_voltage") or data.get("voltage"),
            "current": data.get("battery_current") or data.get("current"),
            "health": data.get("battery_health") or data.get("health"),
            "raw": data
        }

    def chip_temperature(self):
        raw = self.manager.send_command("power info")
        for line in raw.splitlines():
            if "temp" in line.lower() and ":" in line:
                _, _, value = line.partition(":")
                return value.strip()
        return None

    def storage_status(self, mount="/ext"):
        raw = self.manager.send_command(f"storage info {mount}")
        return self._parse_kv_block(raw)

    def full_report(self):
        return {
            "battery": self.battery_status(),
            "temperature_c": self.chip_temperature(),
            "storage": self.storage_status(),
            "timestamp": time.time()
        }

    def full_report_json(self):
        return json.dumps(self.full_report(), indent=2, ensure_ascii=False)


class FlipperNFC:
    def __init__(self, manager):
        self.manager = manager

    def _parse_uid_block(self, raw):
        result = {"found": False, "uid": None, "type": None, "raw": raw}
        for line in raw.splitlines():
            lower = line.lower()
            if "uid" in lower and ":" in line:
                _, _, value = line.partition(":")
                result["uid"] = value.strip()
                result["found"] = True
            if "type" in lower and ":" in line:
                _, _, value = line.partition(":")
                result["type"] = value.strip()
        return result

    def scan(self, timeout_s=5):
        raw = self.manager.send_command("nfc detect", max_wait=timeout_s + 2)
        return self._parse_uid_block(raw)

    def scan_json(self, timeout_s=5):
        return json.dumps(self.scan(timeout_s=timeout_s), indent=2, ensure_ascii=False)

    def read_lf_uid(self, timeout_s=5):
        raw = self.manager.send_command("rfid read", max_wait=timeout_s + 2)
        return self._parse_uid_block(raw)

    def read_lf_uid_json(self, timeout_s=5):
        return json.dumps(self.read_lf_uid(timeout_s=timeout_s), indent=2, ensure_ascii=False)


class FlipperSubGHz:
    def __init__(self, manager):
        self.manager = manager

    def capture(self, frequency_hz, duration_s, filename):
        if not filename.endswith(".sub"):
            filename += ".sub"
        remote_path = f"/ext/subghz/{filename}"
        self.manager.send_command(f"subghz rx {frequency_hz} {remote_path}", wait=0.5, max_wait=duration_s + 5)
        time.sleep(duration_s)
        self.manager.send_command("\x03", wait=0.3, max_wait=3)
        return remote_path

    def list_captures(self, mount="/ext/subghz"):
        raw = self.manager.send_command(f"storage list {mount}")
        return [line.strip() for line in raw.splitlines() if line.strip().endswith(".sub")]


class FlipperBridge:
    def __init__(self, port=None, baudrate=115200, timeout=2.0):
        self.manager = FlipperSerialManager(port=port, baudrate=baudrate, timeout=timeout)
        self.telemetry = FlipperTelemetry(self.manager)
        self.nfc = FlipperNFC(self.manager)
        self.subghz = FlipperSubGHz(self.manager)

    def connect(self):
        return self.manager.connect()

    def disconnect(self):
        self.manager.disconnect()

    def reconnect(self):
        return self.manager.reconnect()

    @property
    def is_connected(self):
        return self.manager.is_connected

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


def build_cli():
    parser = argparse.ArgumentParser(prog="flipperbridge")
    parser.add_argument("--port", default=None)
    parser.add_argument("--baudrate", type=int, default=115200)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("telemetry")

    nfc_parser = subparsers.add_parser("nfc-scan")
    nfc_parser.add_argument("--timeout", type=int, default=5)

    lf_parser = subparsers.add_parser("rfid-scan")
    lf_parser.add_argument("--timeout", type=int, default=5)

    sub_parser = subparsers.add_parser("subghz-capture")
    sub_parser.add_argument("--frequency", type=int, required=True)
    sub_parser.add_argument("--duration", type=int, required=True)
    sub_parser.add_argument("--output", required=True)

    subparsers.add_parser("subghz-list")

    return parser


def main():
    parser = build_cli()
    args = parser.parse_args()

    bridge = FlipperBridge(port=args.port, baudrate=args.baudrate)

    try:
        bridge.connect()
    except FlipperError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)

    try:
        if args.command == "telemetry":
            print(bridge.telemetry.full_report_json())
        elif args.command == "nfc-scan":
            print(bridge.nfc.scan_json(timeout_s=args.timeout))
        elif args.command == "rfid-scan":
            print(bridge.nfc.read_lf_uid_json(timeout_s=args.timeout))
        elif args.command == "subghz-capture":
            path = bridge.subghz.capture(args.frequency, args.duration, args.output)
            print(json.dumps({"saved_to": path}, ensure_ascii=False))
        elif args.command == "subghz-list":
            print(json.dumps(bridge.subghz.list_captures(), ensure_ascii=False))
    except FlipperError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
    finally:
        bridge.disconnect()


if __name__ == "__main__":
    main()
